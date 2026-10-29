"""Theme use cases: the admin edits a draft and publishes it; every role of the tenant reads the published one.

Theme images follow the same registry as item images (media module): an image is attached when a draft
first uses it and discarded once neither the draft nor the published theme uses it, so the tables never
lose an image they are still showing while the admin tries another one in the draft.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.modules.theming.domain.repository import PublishedThemeCache, ThemeRecord, ThemeRepository
from app.modules.theming.domain.theme import Theme, default_theme, parse_theme
from app.shared.domain.images import (
    ALLOWED_FORMATS,
    ImageCleanupScheduler,
    ImageKind,
    ImageRegistry,
    ImageStorage,
    InvalidImage,
    StoredImage,
    UploadSignature,
    new_image_public_id,
    validate_stored_image,
)
from app.shared.domain.ports import Clock, UnitOfWork

THEME_IMAGE_KINDS = (ImageKind.LOGO, ImageKind.BANNER, ImageKind.BACKGROUND)


@dataclass(frozen=True)
class ThemeState:
    draft: Theme
    published: Theme | None
    published_at: datetime | None

    @property
    def has_unpublished_changes(self) -> bool:
        return self.draft != (self.published or default_theme())


def _state(record: ThemeRecord | None) -> ThemeState:
    if record is None:
        return ThemeState(draft=default_theme(), published=None, published_at=None)
    return ThemeState(draft=record.draft, published=record.published, published_at=record.published_at)


def _in_use(record: ThemeRecord | None) -> set[str]:
    if record is None:
        return set()
    return record.draft.image_ids() | (record.published.image_ids() if record.published else set())


class GetThemeDraft:
    def __init__(self, themes: ThemeRepository) -> None:
        self._themes = themes

    async def execute(self, tenant_id: uuid.UUID) -> ThemeState:
        return _state(await self._themes.get(tenant_id))


class GetPublishedTheme:
    """What the tables see: the published theme, or the defaults until the admin publishes one."""

    def __init__(self, themes: ThemeRepository) -> None:
        self._themes = themes

    async def execute(self, tenant_id: uuid.UUID) -> Theme:
        record = await self._themes.get(tenant_id)
        if record is None or record.published is None:
            return default_theme()
        return record.published


class RequestThemeImageUpload:
    """Signs one direct upload to a new public id inside the tenant's folder for a theme slot."""

    def __init__(self, images: ImageStorage, registry: ImageRegistry, uow: UnitOfWork) -> None:
        self._images = images
        self._registry = registry
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, kind: ImageKind) -> UploadSignature:
        if kind not in THEME_IMAGE_KINDS:
            raise InvalidImage("Unknown theme image slot")
        public_id = new_image_public_id(tenant_id, kind)
        signature = self._images.sign_upload(public_id, ALLOWED_FORMATS[kind])
        await self._registry.register(tenant_id, public_id)
        await self._uow.commit()
        return signature


class SaveThemeDraft:
    def __init__(
        self,
        themes: ThemeRepository,
        images: ImageStorage,
        registry: ImageRegistry,
        uow: UnitOfWork,
        cleanup: ImageCleanupScheduler,
    ) -> None:
        self._themes = themes
        self._images = images
        self._registry = registry
        self._uow = uow
        self._cleanup = cleanup

    async def execute(self, tenant_id: uuid.UUID, document: Any) -> ThemeState:
        theme = parse_theme(document, tenant_id)
        slots = theme.images()

        # Only images the theme does not use yet need the storage. Its calls are slow and may fail, so the
        # short read that tells which ones are new ends (releasing the connection) before calling it.
        new = slots.keys() - _in_use(await self._themes.get(tenant_id))
        await self._uow.commit()
        stored: dict[str, StoredImage] = {}
        for public_id in sorted(new):
            found = await self._images.find(public_id)
            if found is None:
                raise InvalidImage("Image not found; upload it first")
            stored[public_id] = found
        for public_id, image in stored.items():
            try:
                validate_stored_image(image, slots[public_id])
            except InvalidImage:
                # Useless upload: let the worker delete it (only while no theme uses it).
                await self._registry.reject(tenant_id, public_id)
                await self._uow.commit()
                await self._cleanup.request_cleanup()
                raise

        record = await self._themes.lock(tenant_id, default_theme())
        in_use = _in_use(record)
        for public_id in slots.keys() - in_use:
            # Only an id signed for this tenant and never used can be attached. One that was in use when
            # read above but was dropped since (another save) is not looked up again: it is not available.
            if public_id not in stored or not await self._registry.attach(tenant_id, public_id):
                raise InvalidImage("Use an image uploaded for this slot; that one is not available")
        published = record.published.image_ids() if record.published else set()
        dropped = record.draft.image_ids() - slots.keys() - published
        for public_id in dropped:
            await self._registry.discard(tenant_id, public_id)
        updated = replace(record, draft=theme)
        await self._themes.update(updated)
        await self._uow.commit()
        if dropped:
            await self._cleanup.request_cleanup()
        return _state(updated)


class PublishTheme:
    def __init__(
        self,
        themes: ThemeRepository,
        registry: ImageRegistry,
        uow: UnitOfWork,
        cleanup: ImageCleanupScheduler,
        cache: PublishedThemeCache,
        clock: Clock,
    ) -> None:
        self._themes = themes
        self._registry = registry
        self._uow = uow
        self._cleanup = cleanup
        self._cache = cache
        self._clock = clock

    async def execute(self, tenant_id: uuid.UUID) -> ThemeState:
        record = await self._themes.lock(tenant_id, default_theme())
        previous = record.published.image_ids() if record.published else set()
        dropped = previous - record.draft.image_ids()
        for public_id in dropped:
            await self._registry.discard(tenant_id, public_id)
        updated = replace(record, published=record.draft, published_at=self._clock.now())
        await self._themes.update(updated)
        await self._uow.commit()
        await self._cache.invalidate(tenant_id)
        if dropped:
            await self._cleanup.request_cleanup()
        return _state(updated)
