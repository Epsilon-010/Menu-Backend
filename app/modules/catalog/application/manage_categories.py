"""Admin use cases over the tenant's menu categories.

Every lookup is scoped to the admin's tenant: another tenant's categories are reported as not found.
"""

import uuid
from dataclasses import dataclass

from app.modules.catalog.domain.catalog import (
    Category,
    CategoryRepository,
    Item,
    ItemRepository,
    ensure_complete_order,
    validate_category_name,
)
from app.modules.catalog.domain.errors import CategoryNameNotAvailable, CategoryNotFound
from app.shared.domain.ports import UnitOfWork


@dataclass(frozen=True)
class CategoryWithItems:
    category: Category
    items: list[Item]


async def get_category(categories: CategoryRepository, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    category = await categories.get(tenant_id, category_id)
    if category is None:
        raise CategoryNotFound(category_id)
    return category


async def _ensure_name_available(
    categories: CategoryRepository, tenant_id: uuid.UUID, name: str, category_id: uuid.UUID | None = None
) -> None:
    existing = await categories.get_by_name(tenant_id, name)
    if existing is not None and existing.id != category_id:
        raise CategoryNameNotAvailable(name)


class CreateCategory:
    """New categories go last in the menu."""

    def __init__(self, categories: CategoryRepository, uow: UnitOfWork) -> None:
        self._categories = categories
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, name: str) -> Category:
        name = validate_category_name(name)
        await _ensure_name_available(self._categories, tenant_id, name)

        category = Category.create(tenant_id, name, await self._categories.next_position(tenant_id))
        await self._categories.add(category)
        await self._uow.commit()
        return category


class ListCatalog:
    """The whole catalog of the tenant in menu order, hidden entries included (admin view)."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository) -> None:
        self._categories = categories
        self._items = items

    async def execute(self, tenant_id: uuid.UUID) -> list[CategoryWithItems]:
        items_by_category: dict[uuid.UUID, list[Item]] = {}
        for item in await self._items.list(tenant_id):
            items_by_category.setdefault(item.category_id, []).append(item)
        return [
            CategoryWithItems(category=category, items=items_by_category.get(category.id, []))
            for category in await self._categories.list(tenant_id)
        ]


class UpdateCategory:
    """Renames, hides or shows a category."""

    def __init__(self, categories: CategoryRepository, uow: UnitOfWork) -> None:
        self._categories = categories
        self._uow = uow

    async def execute(
        self, tenant_id: uuid.UUID, category_id: uuid.UUID, name: str | None = None, is_visible: bool | None = None
    ) -> Category:
        category = await get_category(self._categories, tenant_id, category_id)
        updated = category.with_changes(name=name, is_visible=is_visible)
        if updated.name != category.name:
            await _ensure_name_available(self._categories, tenant_id, updated.name, category_id)

        await self._categories.update(updated)
        await self._uow.commit()
        return updated


class DeleteCategory:
    """Only an empty category can be deleted; the repository enforces it even under concurrency."""

    def __init__(self, categories: CategoryRepository, uow: UnitOfWork) -> None:
        self._categories = categories
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> None:
        await get_category(self._categories, tenant_id, category_id)
        await self._categories.delete(tenant_id, category_id)
        await self._uow.commit()


class ReorderCategories:
    def __init__(self, categories: CategoryRepository, uow: UnitOfWork) -> None:
        self._categories = categories
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        current = await self._categories.list(tenant_id)
        ensure_complete_order((category.id for category in current), ordered_ids)
        await self._categories.set_positions(tenant_id, ordered_ids)
        await self._uow.commit()
