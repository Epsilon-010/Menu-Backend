import uuid

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.domain.catalog import Category, Item
from app.modules.catalog.domain.errors import (
    CatalogIdTaken,
    CategoryNameNotAvailable,
    CategoryNotEmpty,
    CategoryNotFound,
    InvalidCatalogData,
    ItemNotFound,
)
from app.modules.catalog.infrastructure.models import CategoryModel, ItemModel
from app.shared.infrastructure.database import (
    affected_rows,
    advisory_xact_lock,
    violated_foreign_key,
    violated_unique_constraint,
)

_CATEGORY_NAME_INDEX = "uq_categories_tenant_id_lower_name"
_ITEM_CATEGORY_FK = "fk_items_category_id_tenant_id_categories"
_CATEGORY_PK = "pk_categories"
_ITEM_PK = "pk_items"


def _category(model: CategoryModel) -> Category:
    return Category(
        id=model.id, tenant_id=model.tenant_id, name=model.name, position=model.position, is_visible=model.is_visible
    )


def _item(model: ItemModel) -> Item:
    return Item(
        id=model.id,
        tenant_id=model.tenant_id,
        category_id=model.category_id,
        name=model.name,
        description=model.description,
        price_cents=model.price_cents,
        position=model.position,
        is_available=model.is_available,
        image_public_id=model.image_public_id,
        badges=tuple(model.badges),
    )


def _ensure_whole_order(result: object, ordered_ids: list[uuid.UUID]) -> None:
    """A reorder must move every listed row; fewer means one was deleted meanwhile."""
    if affected_rows(result) != len(ordered_ids):
        raise InvalidCatalogData("The menu changed meanwhile; reload it and try again")


def _raise_category_gone(error: IntegrityError, item: Item) -> None:
    """The category was deleted (or never was the tenant's) after the use case checked it."""
    if violated_foreign_key(error) == _ITEM_CATEGORY_FK:
        raise CategoryNotFound(item.category_id) from error


def _raise_name_taken(error: IntegrityError, category: Category) -> None:
    """Another request took the name after the use case checked it."""
    if violated_unique_constraint(error) == _CATEGORY_NAME_INDEX:
        raise CategoryNameNotAvailable(category.name) from error


def _raise_id_taken(error: IntegrityError, primary_key: str, entity_id: uuid.UUID) -> None:
    """A client-supplied id already exists: a concurrent replay of the same create (or a clash)."""
    if violated_unique_constraint(error) == primary_key:
        raise CatalogIdTaken(entity_id) from error


class SqlAlchemyCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, category: Category) -> None:
        self._session.add(
            CategoryModel(
                id=category.id,
                tenant_id=category.tenant_id,
                name=category.name,
                position=category.position,
                is_visible=category.is_visible,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            _raise_id_taken(error, _CATEGORY_PK, category.id)
            _raise_name_taken(error, category)
            raise

    async def get(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        model = await self._session.scalar(
            select(CategoryModel).where(CategoryModel.tenant_id == tenant_id, CategoryModel.id == category_id)
        )
        return _category(model) if model is not None else None

    async def get_for_update(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        model = await self._session.scalar(
            select(CategoryModel)
            .where(CategoryModel.tenant_id == tenant_id, CategoryModel.id == category_id)
            .with_for_update()
        )
        return _category(model) if model is not None else None

    async def exists_anywhere(self, category_id: uuid.UUID) -> bool:
        # Tells a clash with another tenant's id apart from a free id, without reading that row.
        return await self._session.scalar(select(CategoryModel.id).where(CategoryModel.id == category_id)) is not None

    async def lock_order(self, tenant_id: uuid.UUID) -> None:
        # Positions are max + 1 or rewritten whole: changes to one list run one after another.
        await advisory_xact_lock(self._session, f"catalog-order:{tenant_id}")

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Category | None:
        model = await self._session.scalar(
            select(CategoryModel).where(
                CategoryModel.tenant_id == tenant_id, func.lower(CategoryModel.name) == name.lower()
            )
        )
        return _category(model) if model is not None else None

    async def next_position(self, tenant_id: uuid.UUID) -> int:
        last = await self._session.scalar(
            select(func.max(CategoryModel.position)).where(CategoryModel.tenant_id == tenant_id)
        )
        return 0 if last is None else last + 1

    async def update(self, category: Category) -> None:
        try:
            result = await self._session.execute(
                update(CategoryModel)
                .where(CategoryModel.tenant_id == category.tenant_id, CategoryModel.id == category.id)
                .values(name=category.name, is_visible=category.is_visible)
            )
        except IntegrityError as error:
            _raise_name_taken(error, category)
            raise
        if not affected_rows(result):
            raise CategoryNotFound(category.id)

    async def delete(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> None:
        try:
            result = await self._session.execute(
                delete(CategoryModel).where(CategoryModel.tenant_id == tenant_id, CategoryModel.id == category_id)
            )
        except IntegrityError as error:
            if violated_foreign_key(error) == _ITEM_CATEGORY_FK:
                raise CategoryNotEmpty(category_id) from error
            raise
        if not affected_rows(result):
            raise CategoryNotFound(category_id)

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        if not ordered_ids:
            return
        positions = {category_id: position for position, category_id in enumerate(ordered_ids)}
        result = await self._session.execute(
            update(CategoryModel)
            .where(CategoryModel.tenant_id == tenant_id, CategoryModel.id.in_(ordered_ids))
            .values(position=case(positions, value=CategoryModel.id))
        )
        _ensure_whole_order(result, ordered_ids)

    # Last on purpose: a method named `list` shadows the builtin in the annotations below it.
    async def list(self, tenant_id: uuid.UUID) -> list[Category]:
        models = await self._session.scalars(
            select(CategoryModel)
            .where(CategoryModel.tenant_id == tenant_id)
            .order_by(CategoryModel.position, func.lower(CategoryModel.name))
        )
        return [_category(model) for model in models]


class SqlAlchemyItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, item: Item) -> None:
        self._session.add(
            ItemModel(
                id=item.id,
                tenant_id=item.tenant_id,
                category_id=item.category_id,
                name=item.name,
                description=item.description,
                price_cents=item.price_cents,
                position=item.position,
                is_available=item.is_available,
                image_public_id=item.image_public_id,
                badges=list(item.badges),
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            _raise_id_taken(error, _ITEM_PK, item.id)
            _raise_category_gone(error, item)
            raise

    async def get(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item | None:
        model = await self._session.scalar(
            select(ItemModel).where(ItemModel.tenant_id == tenant_id, ItemModel.id == item_id)
        )
        return _item(model) if model is not None else None

    async def get_for_update(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item | None:
        model = await self._session.scalar(
            select(ItemModel).where(ItemModel.tenant_id == tenant_id, ItemModel.id == item_id).with_for_update()
        )
        return _item(model) if model is not None else None

    async def exists_anywhere(self, item_id: uuid.UUID) -> bool:
        return await self._session.scalar(select(ItemModel.id).where(ItemModel.id == item_id)) is not None

    async def lock_order(self, tenant_id: uuid.UUID, category_ids: list[uuid.UUID]) -> None:
        # Always in the same order, so two moves between the same categories cannot deadlock.
        for category_id in sorted(set(category_ids)):
            await advisory_xact_lock(self._session, f"catalog-items-order:{tenant_id}:{category_id}")

    async def list_in_category(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> list[Item]:
        models = await self._session.scalars(
            select(ItemModel)
            .where(ItemModel.tenant_id == tenant_id, ItemModel.category_id == category_id)
            .order_by(ItemModel.position, func.lower(ItemModel.name))
        )
        return [_item(model) for model in models]

    async def next_position(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> int:
        last = await self._session.scalar(
            select(func.max(ItemModel.position)).where(
                ItemModel.tenant_id == tenant_id, ItemModel.category_id == category_id
            )
        )
        return 0 if last is None else last + 1

    async def update(self, item: Item) -> None:
        try:
            result = await self._session.execute(
                update(ItemModel)
                .where(ItemModel.tenant_id == item.tenant_id, ItemModel.id == item.id)
                .values(
                    category_id=item.category_id,
                    name=item.name,
                    description=item.description,
                    price_cents=item.price_cents,
                    position=item.position,
                    is_available=item.is_available,
                    image_public_id=item.image_public_id,
                    badges=list(item.badges),
                )
            )
        except IntegrityError as error:
            _raise_category_gone(error, item)
            raise
        if not affected_rows(result):
            raise ItemNotFound(item.id)

    async def delete(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> None:
        result = await self._session.execute(
            delete(ItemModel).where(ItemModel.tenant_id == tenant_id, ItemModel.id == item_id)
        )
        if not affected_rows(result):
            raise ItemNotFound(item_id)

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        if not ordered_ids:
            return
        positions = {item_id: position for position, item_id in enumerate(ordered_ids)}
        result = await self._session.execute(
            update(ItemModel)
            .where(ItemModel.tenant_id == tenant_id, ItemModel.id.in_(ordered_ids))
            .values(position=case(positions, value=ItemModel.id))
        )
        _ensure_whole_order(result, ordered_ids)

    async def list(self, tenant_id: uuid.UUID) -> list[Item]:
        models = await self._session.scalars(
            select(ItemModel)
            .where(ItemModel.tenant_id == tenant_id)
            .order_by(ItemModel.position, func.lower(ItemModel.name))
        )
        return [_item(model) for model in models]
