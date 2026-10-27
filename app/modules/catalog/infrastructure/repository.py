import uuid

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.domain.catalog import Category, Item
from app.modules.catalog.domain.errors import CategoryNameNotAvailable, CategoryNotEmpty, CategoryNotFound
from app.modules.catalog.infrastructure.models import CategoryModel, ItemModel
from app.shared.infrastructure.database import violated_foreign_key, violated_unique_constraint

_CATEGORY_NAME_INDEX = "uq_categories_tenant_id_lower_name"
_ITEM_CATEGORY_FK = "fk_items_category_id_tenant_id_categories"


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
    )


def _raise_category_gone(error: IntegrityError, item: Item) -> None:
    """The category was deleted (or never was the tenant's) after the use case checked it."""
    if violated_foreign_key(error) == _ITEM_CATEGORY_FK:
        raise CategoryNotFound(item.category_id) from error


def _raise_name_taken(error: IntegrityError, category: Category) -> None:
    """Another request took the name after the use case checked it."""
    if violated_unique_constraint(error) == _CATEGORY_NAME_INDEX:
        raise CategoryNameNotAvailable(category.name) from error


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
            _raise_name_taken(error, category)
            raise

    async def get(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        model = await self._session.scalar(
            select(CategoryModel).where(CategoryModel.tenant_id == tenant_id, CategoryModel.id == category_id)
        )
        return _category(model) if model is not None else None

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
            await self._session.execute(
                update(CategoryModel)
                .where(CategoryModel.tenant_id == category.tenant_id, CategoryModel.id == category.id)
                .values(name=category.name, is_visible=category.is_visible)
            )
        except IntegrityError as error:
            _raise_name_taken(error, category)
            raise

    async def delete(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> None:
        try:
            await self._session.execute(
                delete(CategoryModel).where(CategoryModel.tenant_id == tenant_id, CategoryModel.id == category_id)
            )
        except IntegrityError as error:
            if violated_foreign_key(error) == _ITEM_CATEGORY_FK:
                raise CategoryNotEmpty(category_id) from error
            raise

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        if not ordered_ids:
            return
        positions = {category_id: position for position, category_id in enumerate(ordered_ids)}
        await self._session.execute(
            update(CategoryModel)
            .where(CategoryModel.tenant_id == tenant_id, CategoryModel.id.in_(ordered_ids))
            .values(position=case(positions, value=CategoryModel.id))
        )

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
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            _raise_category_gone(error, item)
            raise

    async def image_in_use(self, tenant_id: uuid.UUID, public_id: str, except_item_id: uuid.UUID) -> bool:
        found = await self._session.scalar(
            select(ItemModel.id)
            .where(
                ItemModel.tenant_id == tenant_id,
                ItemModel.image_public_id == public_id,
                ItemModel.id != except_item_id,
            )
            .limit(1)
        )
        return found is not None

    async def get(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item | None:
        model = await self._session.scalar(
            select(ItemModel).where(ItemModel.tenant_id == tenant_id, ItemModel.id == item_id)
        )
        return _item(model) if model is not None else None

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
            await self._session.execute(
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
                )
            )
        except IntegrityError as error:
            _raise_category_gone(error, item)
            raise

    async def delete(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> None:
        await self._session.execute(delete(ItemModel).where(ItemModel.tenant_id == tenant_id, ItemModel.id == item_id))

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        if not ordered_ids:
            return
        positions = {item_id: position for position, item_id in enumerate(ordered_ids)}
        await self._session.execute(
            update(ItemModel)
            .where(ItemModel.tenant_id == tenant_id, ItemModel.id.in_(ordered_ids))
            .values(position=case(positions, value=ItemModel.id))
        )

    async def list(self, tenant_id: uuid.UUID) -> list[Item]:
        models = await self._session.scalars(
            select(ItemModel)
            .where(ItemModel.tenant_id == tenant_id)
            .order_by(ItemModel.position, func.lower(ItemModel.name))
        )
        return [_item(model) for model in models]
