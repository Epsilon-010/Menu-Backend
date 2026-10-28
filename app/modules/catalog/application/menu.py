"""What tables see of the catalog, and what orders read from it (other modules use these, never the repositories)."""

import uuid

from app.modules.catalog.application.manage_categories import CategoryWithItems, ListCatalog
from app.modules.catalog.domain.catalog import CategoryRepository, Item, ItemRepository


class GetMenu:
    """The menu a table sees: visible categories that have available items, in menu order."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository) -> None:
        self._catalog = ListCatalog(categories, items)

    async def execute(self, tenant_id: uuid.UUID) -> list[CategoryWithItems]:
        menu = []
        for entry in await self._catalog.execute(tenant_id):
            available = [item for item in entry.items if item.is_available]
            if entry.category.is_visible and available:
                menu.append(CategoryWithItems(category=entry.category, items=available))
        return menu


class GetOrderableItems:
    """Items a table may order right now (available and in a visible category), by id, with their current price."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository) -> None:
        self._menu = GetMenu(categories, items)

    async def execute(self, tenant_id: uuid.UUID, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, Item]:
        if not item_ids:
            return {}
        return {
            item.id: item
            for entry in await self._menu.execute(tenant_id)
            for item in entry.items
            if item.id in item_ids
        }
