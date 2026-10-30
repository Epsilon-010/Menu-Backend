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


class GetMenu:
    """The menu a table sees: visible categories that have orderable items, in menu order.

    An item is orderable when it is available and each of its groups has enough available options.
    """

    def __init__(self, categories: CategoryRepository, items: ItemRepository, groups: ModifierGroupRepository) -> None:
        self._catalog = ListCatalog(categories, items)
        self._groups = groups

    async def execute(self, tenant_id: uuid.UUID) -> list[MenuCategory]:
        library = {group.id: group for group in await self._groups.list(tenant_id)}
        menu = []
        for entry in await self._catalog.execute(tenant_id):
            orderable = []
            for item in entry.items:
                groups = tuple(library[group_id] for group_id in item.modifier_group_ids if group_id in library)
                if item.is_available and all(group.can_be_met() for group in groups):
                    orderable.append(MenuItem(item=item, modifier_groups=groups))
            if entry.category.is_visible and orderable:
                menu.append(MenuCategory(category=entry.category, items=orderable))
        return menu


class GetOrderableItems:
    """Items a table may order right now, by id, with their current price and modifier groups."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository, groups: ModifierGroupRepository) -> None:
        self._menu = GetMenu(categories, items, groups)

    async def execute(self, tenant_id: uuid.UUID, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, MenuItem]:
        if not item_ids:
            return {}
        return {
            entry.item.id: entry
            for category in await self._menu.execute(tenant_id)
            for entry in category.items
            if entry.item.id in item_ids
        }
