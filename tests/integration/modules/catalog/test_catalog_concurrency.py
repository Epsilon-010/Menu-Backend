"""Concurrent catalog writes against real Postgres: no lost update, no duplicate, no shared position.

The slow repositories pause right after every read, so without row or order locks two concurrent
requests would both read the same state before either writes (the race these tests reproduce).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.catalog.application.item_images import RequestImageUpload, SetItemImage
from app.modules.catalog.application.manage_categories import CreateCategory, ListCatalog, UpdateCategory
from app.modules.catalog.application.manage_items import CreateItem, ItemChanges, ItemDraft, UpdateItem
from app.modules.catalog.infrastructure.repository import SqlAlchemyCategoryRepository, SqlAlchemyItemRepository
from app.modules.media.infrastructure.repository import SqlAlchemyImageUploads
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import _seed
from tests.unit.fakes import FakeCleanupScheduler, FakeImageStorage

T = TypeVar("T")
PAUSE = 0.15


class SlowCategories(SqlAlchemyCategoryRepository):
    async def get(self, *args: Any) -> Any:
        found = await super().get(*args)
        await asyncio.sleep(PAUSE)
        return found

    async def get_for_update(self, *args: Any) -> Any:
        found = await super().get_for_update(*args)
        await asyncio.sleep(PAUSE)
        return found

    async def next_position(self, *args: Any) -> int:
        position = await super().next_position(*args)
        await asyncio.sleep(PAUSE)
        return position


class SlowItems(SqlAlchemyItemRepository):
    async def get_for_update(self, *args: Any) -> Any:
        found = await super().get_for_update(*args)
        await asyncio.sleep(PAUSE)
        return found


@pytest.fixture
def tenant() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


def _run(work: Callable[[async_sessionmaker[AsyncSession]], Awaitable[T]]) -> T:
    async def run() -> T:
        engine = create_engine(get_settings().database_url)
        try:
            return await work(create_session_factory(engine))
        finally:
            await engine.dispose()

    return asyncio.run(run())


async def _in_session(factory: async_sessionmaker[AsyncSession], work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async with factory() as session:
        return await work(session)


def test_concurrent_replays_of_one_create_make_a_single_category(tenant: SeedResult) -> None:
    category_id = uuid.uuid4()

    async def create(session: AsyncSession) -> uuid.UUID:
        use_case = CreateCategory(SlowCategories(session), SqlAlchemyUnitOfWork(session))
        return (await use_case.execute(tenant.tenant_id, "Tacos", category_id)).id

    async def work(factory: async_sessionmaker[AsyncSession]) -> tuple[list[uuid.UUID], int]:
        ids = await asyncio.gather(*(_in_session(factory, create) for _ in range(3)))
        listed = await _in_session(
            factory, lambda s: ListCatalog(SqlAlchemyCategoryRepository(s), SqlAlchemyItemRepository(s)).execute(tenant.tenant_id)
        )
        return list(ids), len(listed)

    ids, count = _run(work)

    assert ids == [category_id] * 3
    assert count == 1


def test_concurrent_creates_never_share_a_position(tenant: SeedResult) -> None:
    async def create(name: str) -> Callable[[AsyncSession], Awaitable[int]]:
        async def run(session: AsyncSession) -> int:
            use_case = CreateCategory(SlowCategories(session), SqlAlchemyUnitOfWork(session))
            return (await use_case.execute(tenant.tenant_id, name)).position

        return run

    async def work(factory: async_sessionmaker[AsyncSession]) -> list[int]:
        runs = [await create(name) for name in ("Tacos", "Bebidas", "Postres", "Salsas")]
        return list(await asyncio.gather(*(_in_session(factory, run) for run in runs)))

    assert sorted(_run(work)) == [0, 1, 2, 3]


def test_concurrent_edits_of_one_category_both_survive(tenant: SeedResult) -> None:
    async def work(factory: async_sessionmaker[AsyncSession]) -> tuple[str, bool]:
        category = await _in_session(
            factory,
            lambda s: CreateCategory(SqlAlchemyCategoryRepository(s), SqlAlchemyUnitOfWork(s)).execute(
                tenant.tenant_id, "Tacos"
            ),
        )

        def edit(**changes: Any) -> Callable[[AsyncSession], Awaitable[Any]]:
            return lambda s: UpdateCategory(SlowCategories(s), SqlAlchemyUnitOfWork(s)).execute(
                tenant.tenant_id, category.id, **changes
            )

        await asyncio.gather(_in_session(factory, edit(name="Tacos al carbón")), _in_session(factory, edit(is_visible=False)))
        final = await _in_session(factory, lambda s: SqlAlchemyCategoryRepository(s).get(tenant.tenant_id, category.id))
        assert final is not None
        return final.name, final.is_visible

    assert _run(work) == ("Tacos al carbón", False)


def test_an_edit_racing_an_image_change_never_resurrects_the_old_image(tenant: SeedResult) -> None:
    """Verifier A2: a rename that read the item before an image replace must not write the old image
    back (the old one would then be deleted while the item still shows it)."""
    images = FakeImageStorage()
    cleanup = FakeCleanupScheduler()

    async def work(factory: async_sessionmaker[AsyncSession]) -> tuple[Any, dict[str, str], str]:
        async def setup(s: AsyncSession) -> tuple[uuid.UUID, str, str]:
            category = await CreateCategory(SqlAlchemyCategoryRepository(s), SqlAlchemyUnitOfWork(s)).execute(
                tenant.tenant_id, "Tacos"
            )
            draft = ItemDraft(category_id=category.id, name="Pastor", description="", price_cents=2500)
            item = await CreateItem(SqlAlchemyCategoryRepository(s), SqlAlchemyItemRepository(s), SqlAlchemyUnitOfWork(s)).execute(
                tenant.tenant_id, draft
            )
            ids = []
            for _ in range(2):
                signed = await RequestImageUpload(images, SqlAlchemyImageUploads(s), SqlAlchemyUnitOfWork(s)).execute(
                    tenant.tenant_id
                )
                images.upload(signed.public_id)
                ids.append(signed.public_id)
            return item.id, ids[0], ids[1]

        item_id, old, new = await _in_session(factory, setup)

        def set_image(public_id: str) -> Callable[[AsyncSession], Awaitable[Any]]:
            return lambda s: SetItemImage(
                SlowItems(s), images, SqlAlchemyImageUploads(s), SqlAlchemyUnitOfWork(s), cleanup
            ).execute(tenant.tenant_id, item_id, public_id)

        await _in_session(factory, set_image(old))
        rename = lambda s: UpdateItem(SqlAlchemyCategoryRepository(s), SlowItems(s), SqlAlchemyUnitOfWork(s)).execute(  # noqa: E731
            tenant.tenant_id, item_id, ItemChanges(name="Pastor XL")
        )
        await asyncio.gather(_in_session(factory, rename), _in_session(factory, set_image(new)))

        final = await _in_session(factory, lambda s: SqlAlchemyItemRepository(s).get(tenant.tenant_id, item_id))

        async def statuses(s: AsyncSession) -> dict[str, str]:
            from sqlalchemy import select

            from app.modules.media.infrastructure.models import ImageUploadModel

            rows = await s.execute(select(ImageUploadModel.public_id, ImageUploadModel.status))
            return {("old" if public_id == old else "new"): status for public_id, status in rows}

        return final, await _in_session(factory, statuses), new

    final, statuses, new = _run(work)

    # Both edits survive: the new name and the new image, and the registry agrees with the item.
    assert final is not None
    assert final.name == "Pastor XL"
    assert final.image_public_id == new
    assert statuses == {"old": "discarded", "new": "attached"}
