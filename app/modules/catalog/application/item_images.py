"""Item images: the browser uploads to the storage with a signature, then the admin saves the public id.

Cloudinary and Postgres share no transaction, so every signed public id is recorded in the image
registry (media module) first. Attaching, replacing, removing or rejecting an image only changes that
record, in the same transaction as the item; a background worker deletes discarded images and
uploads that were never attached. No request ever waits for a delete in the storage.
"""

import uuid
from dataclasses import replace

from app.modules.catalog.application.manage_items import get_item
from app.modules.catalog.domain.catalog import Item, ItemRepository
from app.shared.domain.images import (
    ALLOWED_FORMATS,
    ImageCleanupScheduler,
    ImageKind,
    ImageRegistry,
    ImageStorage,
    InvalidImage,
    UploadSignature,
    ensure_owned_image,
    new_image_public_id,
    validate_stored_image,
)
from app.shared.domain.ports import UnitOfWork


class RequestImageUpload:
    """Signs one direct upload to a new public id inside the tenant's items folder and records it."""

    def __init__(self, images: ImageStorage, registry: ImageRegistry, uow: UnitOfWork) -> None:
        self._images = images
        self._registry = registry
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID) -> UploadSignature:
        public_id = new_image_public_id(tenant_id, ImageKind.ITEM)
        signature = self._images.sign_upload(public_id, ALLOWED_FORMATS[ImageKind.ITEM])
        await self._registry.register(tenant_id, public_id)
        await self._uow.commit()
        return signature


class SetItemImage:
    def __init__(
        self,
        items: ItemRepository,
        images: ImageStorage,
        registry: ImageRegistry,
        uow: UnitOfWork,
        cleanup: ImageCleanupScheduler,
    ) -> None:
        self._items = items
        self._images = images
        self._registry = registry
        self._uow = uow
        self._cleanup = cleanup

    async def execute(self, tenant_id: uuid.UUID, item_id: uuid.UUID, public_id: str) -> Item:
        ensure_owned_image(tenant_id, ImageKind.ITEM, public_id)
        # The storage call goes first, before any query: a slow storage must not hold a database
        # connection.
        stored = await self._images.find(public_id)
        if stored is None:
            raise InvalidImage("Image not found; upload it first")

        item = await get_item(self._items, tenant_id, item_id, for_update=True)
        if item.image_public_id == public_id:
            return item
        try:
            validate_stored_image(stored, ImageKind.ITEM)
        except InvalidImage:
            # Useless upload: let the worker delete it (only if no item uses it).
            await self._registry.reject(tenant_id, public_id)
            await self._uow.commit()
            await self._cleanup.request_cleanup()
            raise
        # Only an id signed for this tenant and not used yet can be attached; the conditional
        # update also stops two items from claiming the same image at the same time.
        if not await self._registry.attach(tenant_id, public_id):
            raise InvalidImage("Use an image uploaded for this item; that one is not available")

        if item.image_public_id is not None:
            await self._registry.discard(tenant_id, item.image_public_id)
        updated = replace(item, image_public_id=public_id)
        await self._items.update(updated)
        await self._uow.commit()
        if item.image_public_id is not None:
            await self._cleanup.request_cleanup()
        return updated


class RemoveItemImage:
    def __init__(
        self, items: ItemRepository, registry: ImageRegistry, uow: UnitOfWork, cleanup: ImageCleanupScheduler
    ) -> None:
        self._items = items
        self._registry = registry
        self._uow = uow
        self._cleanup = cleanup

    async def execute(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item:
        item = await get_item(self._items, tenant_id, item_id, for_update=True)
        if item.image_public_id is None:
            return item
        await self._registry.discard(tenant_id, item.image_public_id)
        updated = replace(item, image_public_id=None)
        await self._items.update(updated)
        await self._uow.commit()
        await self._cleanup.request_cleanup()
        return updated
