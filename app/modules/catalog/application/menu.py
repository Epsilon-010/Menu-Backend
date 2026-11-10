"""What tables see of the catalog, and what orders read from it (other modules use these, never the repositories)."""

import uuid
from dataclasses import dataclass

from app.modules.catalog.application.manage_categories import ListCatalog
from app.modules.catalog.domain.catalog import Category, CategoryRepository, Item, ItemRepository
from app.modules.catalog.domain.modifiers import ModifierGroup, ModifierGroupRepository


@dataclass(frozen=True)
class MenuItem:
    """An item a table can order, with its modifier groups in the item's order (sold-out options included)."""

    item: Item
    modifier_groups: tuple[ModifierGroup, ...]


@dataclass(frozen=True)
class MenuCategory:
    category: Category
    items: list[MenuItem]


def _orderable(
    category: Category | None, item: Item, library: dict[uuid.UUID, ModifierGroup]
) -> MenuItem | None:
    """The rule both the menu and the orders follow: the item, available, in a visible category, with
    enough available options in each of its groups. None when it cannot be ordered."""
    groups = tuple(library[group_id] for group_id in item.modifier_group_ids if group_id in library)
    if category is None or not category.is_visible or not item.is_available:
        return None
    if not all(group.can_be_met() for group in groups):
        return None
    return MenuItem(item=item, modifier_groups=groups)


class GetMenu:
    """The menu a table sees: visible categories that have orderable items, in menu order."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository, groups: ModifierGroupRepository) -> None:
        self._catalog = ListCatalog(categories, items)
        self._groups = groups

    async def execute(self, tenant_id: uuid.UUID) -> list[MenuCategory]:
        library = {group.id: group for group in await self._groups.list(tenant_id)}
        menu = []
        for entry in await self._catalog.execute(tenant_id):
            orderable = [
                found for item in entry.items if (found := _orderable(entry.category, item, library)) is not None
            ]
            if orderable:
                menu.append(MenuCategory(category=entry.category, items=orderable))
        return menu


class GetOrderableItems:
    """Items a table may order right now, by id, with their current price and modifier groups."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository, groups: ModifierGroupRepository) -> None:
        self._categories = categories
        self._items = items
        self._groups = groups

    async def execute(self, tenant_id: uuid.UUID, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, MenuItem]:
        if not item_ids:
            return {}
        items = await self._items.list_by_ids(tenant_id, item_ids)
        if not items:
            return {}
        categories = await self._categories.list_by_ids(tenant_id, {item.category_id for item in items})
        by_id = {category.id: category for category in categories}
        group_ids = {group_id for item in items for group_id in item.modifier_group_ids}
        library = {g.id: g for g in await self._groups.list_by_ids(tenant_id, group_ids)} if group_ids else {}
        orderable = (_orderable(by_id.get(item.category_id), item, library) for item in items)
        return {entry.item.id: entry for entry in orderable if entry is not None}
