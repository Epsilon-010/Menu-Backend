"""Admin use cases over the tenant's menu items.

An item always belongs to a category of the same tenant; another tenant's items and categories
are reported as not found.
"""

import uuid
from dataclasses import dataclass, replace

from app.modules.catalog.application.manage_categories import get_category
from app.modules.catalog.domain.catalog import CategoryRepository, Item, ItemRepository, ensure_complete_order
from app.modules.catalog.domain.errors import ItemNotFound
from app.shared.domain.images import ImageCleanupScheduler, ImageRegistry
from app.shared.domain.ports import UnitOfWork


@dataclass(frozen=True)
class ItemDraft:
    category_id: uuid.UUID
    name: str
    description: str
    price_cents: int


@dataclass(frozen=True)
class ItemChanges:
    """Fields left as None keep their value."""

    name: str | None = None
    description: str | None = None
    price_cents: int | None = None
    is_available: bool | None = None
    category_id: uuid.UUID | None = None


async def get_item(items: ItemRepository, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item:
    item = await items.get(tenant_id, item_id)
    if item is None:
        raise ItemNotFound(item_id)
    return item


class CreateItem:
    """New items go last in their category; the image is set afterwards (it is uploaded separately)."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository, uow: UnitOfWork) -> None:
        self._categories = categories
        self._items = items
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, draft: ItemDraft) -> Item:
        await get_category(self._categories, tenant_id, draft.category_id)
        item = Item.create(
            tenant_id,
            draft.category_id,
            draft.name,
            draft.description,
            draft.price_cents,
            await self._items.next_position(tenant_id, draft.category_id),
        )
        await self._items.add(item)
        await self._uow.commit()
        return item


class UpdateItem:
    """Edits an item; moving it to another category puts it last there."""

    def __init__(self, categories: CategoryRepository, items: ItemRepository, uow: UnitOfWork) -> None:
        self._categories = categories
        self._items = items
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, item_id: uuid.UUID, changes: ItemChanges) -> Item:
        item = await get_item(self._items, tenant_id, item_id)
        updated = item.with_changes(
            name=changes.name,
            description=changes.description,
            price_cents=changes.price_cents,
            is_available=changes.is_available,
        )
        if changes.category_id is not None and changes.category_id != item.category_id:
            await get_category(self._categories, tenant_id, changes.category_id)
            position = await self._items.next_position(tenant_id, changes.category_id)
            updated = replace(updated, category_id=changes.category_id, position=position)

        await self._items.update(updated)
        await self._uow.commit()
        return updated


class DeleteItem:
    """Deletes the item; its image is discarded in the same transaction and deleted by the worker."""

    def __init__(
        self, items: ItemRepository, registry: ImageRegistry, uow: UnitOfWork, cleanup: ImageCleanupScheduler
    ) -> None:
        self._items = items
        self._registry = registry
        self._uow = uow
        self._cleanup = cleanup

    async def execute(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> None:
        item = await get_item(self._items, tenant_id, item_id)
        if item.image_public_id is not None:
            await self._registry.discard(tenant_id, item.image_public_id)
        await self._items.delete(tenant_id, item_id)
        await self._uow.commit()
        if item.image_public_id is not None:
            await self._cleanup.request_cleanup()


class ReorderItems:
    def __init__(self, categories: CategoryRepository, items: ItemRepository, uow: UnitOfWork) -> None:
        self._categories = categories
        self._items = items
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, category_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        await get_category(self._categories, tenant_id, category_id)
        current = await self._items.list_in_category(tenant_id, category_id)
        ensure_complete_order((item.id for item in current), ordered_ids)
        await self._items.set_positions(tenant_id, ordered_ids)
        await self._uow.commit()
