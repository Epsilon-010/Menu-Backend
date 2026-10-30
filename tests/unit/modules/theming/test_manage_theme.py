import uuid
from datetime import timedelta
from typing import Any

import pytest

from app.modules.theming.application.manage_theme import (
    GetPublishedTheme,
    GetThemeDraft,
    ImportTheme,
    ListThemeVersions,
    PublishTheme,
    RequestThemeImageUpload,
    SaveThemeDraft,
)
from app.modules.theming.domain.repository import HISTORY_LIMIT
from app.modules.theming.domain.theme import InvalidTheme, default_theme
from app.shared.domain.images import ImageKind, ImageStorageUnavailable, InvalidImage
from tests.unit.fakes import (
    FakeCleanupScheduler,
    FakeClock,
    FakeImageStorage,
    FakePublishedThemeCache,
    FakeUnitOfWork,
    InMemoryImageRegistry,
    InMemoryThemeHistory,
    InMemoryThemeRepository,
)

pytestmark = pytest.mark.anyio

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()


class World:
    def __init__(self) -> None:
        self.themes = InMemoryThemeRepository()
        self.history = InMemoryThemeHistory()
        self.storage = FakeImageStorage()
        self.registry = InMemoryImageRegistry()
        self.uow = FakeUnitOfWork()
        self.cleanup = FakeCleanupScheduler()
        self.cache = FakePublishedThemeCache()
        self.clock = FakeClock()

    def save(self, doc: dict[str, Any], tenant: uuid.UUID = TENANT) -> Any:
        use_case = SaveThemeDraft(self.themes, self.history, self.storage, self.registry, self.uow, self.cleanup)
        return use_case.execute(tenant, doc)

    def publish(self, tenant: uuid.UUID = TENANT) -> Any:
        use_case = PublishTheme(self.themes, self.history, self.registry, self.uow, self.cleanup, self.cache, self.clock)
        return use_case.execute(tenant)

    def versions(self, tenant: uuid.UUID = TENANT) -> Any:
        return ListThemeVersions(self.history).execute(tenant)

    def import_(self, doc: Any, tenant: uuid.UUID = TENANT) -> Any:
        return ImportTheme(self.themes, self.history).execute(tenant, doc)

    def draft(self, tenant: uuid.UUID = TENANT) -> Any:
        return GetThemeDraft(self.themes).execute(tenant)

    def published(self, tenant: uuid.UUID = TENANT) -> Any:
        return GetPublishedTheme(self.themes).execute(tenant)

    async def upload(self, kind: ImageKind, tenant: uuid.UUID = TENANT, image_format: str = "png") -> str:
        signature = await RequestThemeImageUpload(self.storage, self.registry, self.uow).execute(tenant, kind)
        self.storage.upload(signature.public_id, image_format)
        return signature.public_id


@pytest.fixture
def world() -> World:
    return World()


def with_colors(**colors: Any) -> dict[str, Any]:
    doc = default_theme().to_dict()
    doc["colors"].update(colors)
    return doc


def with_logo(public_id: str | None, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = doc or default_theme().to_dict()
    doc["brand"]["logo"]["image_id"] = public_id
    return doc


async def test_a_tenant_without_a_theme_reads_the_defaults(world: World) -> None:
    state = await world.draft()
    assert state.draft == default_theme()
    assert state.published is None and state.published_at is None
    assert state.has_unpublished_changes is False
    assert await world.published() == default_theme()


async def test_the_draft_changes_without_touching_what_tables_see_until_published(world: World) -> None:
    saved = await world.save(with_colors(primary="#123456"))
    assert saved.draft.colors.primary == "#123456"
    assert saved.has_unpublished_changes is True
    assert (await world.published()).colors.primary == default_theme().colors.primary
    assert world.cache.invalidated == []

    published = await world.publish()
    assert published.published == published.draft
    assert published.published_at == world.clock.now()
    assert published.has_unpublished_changes is False
    assert (await world.published()).colors.primary == "#123456"
    assert world.cache.invalidated == [TENANT]


async def test_an_invalid_document_is_rejected_and_nothing_is_saved(world: World) -> None:
    with pytest.raises(InvalidTheme):
        await world.save(with_colors(primary="#fff;}body{display:none"))
    assert (await world.draft()).draft == default_theme()
    assert world.uow.commits == 0


async def test_theme_images_are_signed_in_their_own_folder_and_svg_only_for_logos(world: World) -> None:
    signer = RequestThemeImageUpload(world.storage, world.registry, world.uow)
    logo = await signer.execute(TENANT, ImageKind.LOGO)
    banner = await signer.execute(TENANT, ImageKind.BANNER)
    assert logo.public_id.startswith(f"tenants/{TENANT}/logos/")
    assert "svg" in logo.allowed_formats and "svg" not in banner.allowed_formats
    assert world.registry.status(logo.public_id) == "pending"
    with pytest.raises(InvalidImage):
        await signer.execute(TENANT, ImageKind.ITEM)


async def test_a_new_image_is_attached_and_a_replaced_one_discarded(world: World) -> None:
    first = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(first))
    assert world.registry.status(first) == "attached"

    second = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(second))
    assert world.registry.status(second) == "attached"
    assert world.registry.status(first) == "discarded"
    assert world.cleanup.requests == 1


async def test_an_image_the_published_theme_still_uses_is_kept_until_republished(world: World) -> None:
    first = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(first))
    await world.publish()

    second = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(second))
    assert world.registry.status(first) == "attached"  # the tables still show it

    await world.save(with_logo(first))  # back to the published logo: allowed, nothing new to attach
    assert world.registry.status(second) == "discarded"
    assert world.registry.status(first) == "attached"

    third = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(third))
    await world.publish()
    assert world.registry.status(first) == "attached"  # the first version is in the history
    assert world.registry.status(third) == "attached"


# --- History of published versions


async def test_every_publish_is_kept_newest_first_with_its_number_and_time(world: World) -> None:
    await world.save(with_colors(primary="#111111"))
    await world.publish()
    world.clock.advance(timedelta(minutes=5))
    await world.save(with_colors(primary="#222222"))
    await world.publish()

    versions = await world.versions()
    assert [version.number for version in versions] == [2, 1]
    assert [version.theme.colors.primary for version in versions] == ["#222222", "#111111"]
    assert versions[0].published_at == world.clock.now()
    assert versions[1].published_at == world.clock.now() - timedelta(minutes=5)


async def test_a_tenant_that_never_published_has_no_history(world: World) -> None:
    await world.save(with_colors(primary="#111111"))
    assert await world.versions() == []


async def test_only_the_last_versions_are_kept(world: World) -> None:
    for number in range(HISTORY_LIMIT + 2):
        await world.save(with_colors(primary=f"#0000{number:02x}"))
        await world.publish()

    versions = await world.versions()
    assert HISTORY_LIMIT == 20
    assert len(versions) == HISTORY_LIMIT
    assert [version.number for version in versions] == list(range(HISTORY_LIMIT + 2, 2, -1))
    assert versions[0].theme.colors.primary == f"#0000{HISTORY_LIMIT + 1:02x}"


async def test_an_image_leaves_only_when_no_draft_published_or_kept_version_uses_it(world: World) -> None:
    first = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(first))
    await world.publish()  # version 1 uses it
    await world.save(with_logo(None))
    assert world.registry.status(first) == "attached"  # still published
    for _ in range(HISTORY_LIMIT - 1):
        await world.save(with_colors(primary="#123456"))
        await world.publish()
    assert world.registry.status(first) == "attached"  # version 1 is still the 20th
    assert world.cleanup.requests == 0

    await world.publish()  # version 1 leaves the history
    assert world.registry.status(first) == "discarded"
    assert world.cleanup.requests == 1


async def test_restoring_a_version_puts_its_images_back_in_the_draft_without_the_storage(world: World) -> None:
    first = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(first))
    await world.publish()
    second = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(second))
    await world.publish()

    old = (await world.versions())[1].theme
    world.storage.fail_lookups = True  # an image the history keeps needs no lookup
    state = await world.save(old.to_dict())
    assert state.draft == old
    assert world.registry.status(first) == "attached"
    assert world.registry.status(second) == "attached"  # published and in the history


async def test_a_draft_image_no_version_uses_is_discarded_when_replaced(world: World) -> None:
    await world.publish()
    first = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(first))
    second = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(second))
    assert world.registry.status(first) == "discarded"


async def test_histories_never_mix_between_tenants(world: World) -> None:
    await world.save(with_colors(primary="#111111"))
    await world.publish()
    await world.save(with_colors(primary="#222222"), tenant=OTHER)
    await world.publish(OTHER)

    assert [v.theme.colors.primary for v in await world.versions()] == ["#111111"]
    assert [v.theme.colors.primary for v in await world.versions(OTHER)] == ["#222222"]
    assert [v.number for v in await world.versions(OTHER)] == [1]


async def test_saving_the_same_draft_twice_changes_nothing(world: World) -> None:
    logo = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(logo))
    again = await world.save(with_logo(logo))
    assert again.draft.brand.logo.image_id == logo
    assert world.registry.status(logo) == "attached"


async def test_only_images_signed_for_this_tenant_and_still_pending_can_be_used(world: World) -> None:
    never_signed = f"tenants/{TENANT}/logos/{uuid.uuid4().hex}"
    world.storage.upload(never_signed, "png")
    with pytest.raises(InvalidImage):
        await world.save(with_logo(never_signed))

    missing = await world.upload(ImageKind.LOGO)
    world.storage.stored.clear()
    with pytest.raises(InvalidImage, match="upload it first"):
        await world.save(with_logo(missing))


async def test_a_wrong_format_is_rejected_and_the_upload_marked_for_cleanup(world: World) -> None:
    banner = await world.upload(ImageKind.BANNER, image_format="svg")
    doc = default_theme().to_dict()
    doc["brand"]["banner"]["image_id"] = banner
    with pytest.raises(InvalidImage, match="format"):
        await world.save(doc)
    assert world.registry.status(banner) == "discarded"
    assert world.cleanup.requests == 1
    assert (await world.draft()).draft == default_theme()

    svg_logo = await world.upload(ImageKind.LOGO, image_format="svg")
    assert (await world.save(with_logo(svg_logo))).draft.brand.logo.image_id == svg_logo


async def test_storage_down_only_blocks_saving_a_new_image(world: World) -> None:
    logo = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(logo))
    world.storage.fail_lookups = True
    saved = await world.save(with_logo(logo, with_colors(accent="#00ff00")))
    assert saved.draft.colors.accent == "#00ff00"

    fresh = await world.upload(ImageKind.LOGO)
    with pytest.raises(ImageStorageUnavailable):
        await world.save(with_logo(fresh))


async def test_tenants_never_see_nor_change_each_others_theme(world: World) -> None:
    await world.save(with_colors(primary="#111111"))
    await world.publish()
    assert (await world.draft(OTHER)).draft == default_theme()
    assert await world.published(OTHER) == default_theme()

    others_logo = await world.upload(ImageKind.LOGO, tenant=OTHER)
    with pytest.raises(InvalidTheme):
        await world.save(with_logo(others_logo))
    assert world.registry.status(others_logo) == "pending"


# --- Import


async def test_an_import_keeps_images_any_theme_of_the_tenant_still_uses(world: World) -> None:
    in_history = await world.upload(ImageKind.LOGO)
    await world.save(with_logo(in_history))
    await world.publish()
    in_draft = await world.upload(ImageKind.BANNER)
    doc = with_logo(None)
    doc["brand"]["banner"]["image_id"] = in_draft
    await world.save(doc)  # the logo is now only in the published theme and the history
    unused = await world.upload(ImageKind.BACKGROUND)  # signed, never saved

    exported = with_logo(in_history)
    exported["brand"]["banner"]["image_id"] = in_draft
    exported["brand"]["background"].update(kind="image", image_id=unused)
    imported = await world.import_(exported)

    assert imported.theme.brand.logo.image_id == in_history
    assert imported.theme.brand.banner.image_id == in_draft
    assert imported.theme.brand.background.image_id is None
    assert imported.removed_images == ("background",)


async def test_an_import_changes_nothing_until_the_admin_saves_it(world: World) -> None:
    await world.import_(with_colors(primary="#123456"))
    assert (await world.draft()).draft == default_theme()
    assert world.uow.commits == 0


async def test_an_import_never_keeps_another_tenants_image_even_if_that_tenant_uses_it(world: World) -> None:
    others = await world.upload(ImageKind.LOGO, tenant=OTHER)
    await world.save(with_logo(others), tenant=OTHER)

    imported = await world.import_(with_logo(others))
    assert imported.theme.brand.logo.image_id is None
    assert imported.removed_images == ("logo",)
