"""Item images: the browser uploads to the storage with a signature, then the admin saves the public id.

The previous image is deleted from the storage only after the database change is committed, so a
failed request never leaves an item pointing at a deleted image. A failed cleanup only leaves an
orphan file in the tenant's folder; it is logged and never undoes the committed change.
"""

import logging
import uuid
from dataclasses import replace

from app.modules.catalog.domain.catalog import Item, ItemRepository
from app.modules.catalog.domain.errors import ItemNotFound
from app.shared.domain.images import (
    ALLOWED_FORMATS,
    ImageKind,
    ImageStorage,
    InvalidImage,
    UploadSignature,
    ensure_owned_image,
    new_image_public_id,
    validate_stored_image,
)
from app.shared.domain.ports import UnitOfWork

logger = logging.getLogger(__name__)


async def discard_image(images: ImageStorage, public_id: str | None) -> None:
    if public_id is None:
        return
    try:
        await images.delete(public_id)
    except Exception:
        logger.warning("Could not delete image %s from the storage", public_id, exc_info=True)


async def _get_item(items: ItemRepository, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item:
    item = await items.get(tenant_id, item_id)
    if item is None:
        raise ItemNotFound(item_id)
    return item


class RequestImageUpload:
    """Signs one direct upload to a new public id inside the tenant's items folder."""

    def __init__(self, images: ImageStorage) -> None:
        self._images = images

    async def execute(self, tenant_id: uuid.UUID) -> UploadSignature:
        public_id = new_image_public_id(tenant_id, ImageKind.ITEM)
        return self._images.sign_upload(public_id, ALLOWED_FORMATS[ImageKind.ITEM])


class SetItemImage:
    def __init__(self, items: ItemRepository, images: ImageStorage, uow: UnitOfWork) -> None:
        self._items = items
        self._images = images
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, item_id: uuid.UUID, public_id: str) -> Item:
        item = await _get_item(self._items, tenant_id, item_id)
        ensure_owned_image(tenant_id, ImageKind.ITEM, public_id)
        stored = await self._images.find(public_id)
        if stored is None:
            raise InvalidImage("Image not found; upload it first")
        try:
            validate_stored_image(stored, ImageKind.ITEM)
        except InvalidImage:
            # The upload is inside this tenant's folder and useless: do not keep it.
            await discard_image(self._images, public_id)
            raise

        updated = replace(item, image_public_id=public_id)
        await self._items.update(updated)
        await self._uow.commit()
        if item.image_public_id != public_id:
            await discard_image(self._images, item.image_public_id)
        return updated


class RemoveItemImage:
    def __init__(self, items: ItemRepository, images: ImageStorage, uow: UnitOfWork) -> None:
        self._items = items
        self._images = images
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item:
        item = await _get_item(self._items, tenant_id, item_id)
        updated = replace(item, image_public_id=None)
        await self._items.update(updated)
        await self._uow.commit()
        await discard_image(self._images, item.image_public_id)
        return updated
