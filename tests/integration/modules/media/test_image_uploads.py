"""Guarantees of the image registry that only real Postgres can prove."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.media.infrastructure.repository import SqlAlchemyImageUploads
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import _seed


@pytest.fixture
def tenant() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


async def _with_factory(work):  # type: ignore[no-untyped-def]
    engine = create_engine(get_settings().database_url)
    try:
        return await work(create_session_factory(engine))
    finally:
        await engine.dispose()


async def _register(factory: async_sessionmaker, tenant: SeedResult, *public_ids: str) -> None:  # type: ignore[type-arg]
    async with factory() as session:
        for public_id in public_ids:
            await SqlAlchemyImageUploads(session).register(tenant.tenant_id, public_id)
        await session.commit()


def test_two_concurrent_attaches_of_one_upload_have_a_single_winner(tenant: SeedResult) -> None:
    public_id = f"tenants/{tenant.tenant_id}/items/race"

    async def work(factory: async_sessionmaker) -> list[bool]:  # type: ignore[type-arg]
        await _register(factory, tenant, public_id)

        async def attach() -> bool:
            async with factory() as session:
                won = await SqlAlchemyImageUploads(session).attach(tenant.tenant_id, public_id)
                await asyncio.sleep(0.05)  # keep both transactions open at once
                await session.commit()
                return won

        return list(await asyncio.gather(attach(), attach()))

    assert sorted(asyncio.run(_with_factory(work))) == [False, True]


def test_two_workers_never_claim_the_same_image(tenant: SeedResult) -> None:
    ids = [f"tenants/{tenant.tenant_id}/items/img{index}" for index in range(4)]
    soon = datetime.now(UTC) + timedelta(hours=1)

    async def work(factory: async_sessionmaker) -> tuple[list[str], list[str]]:  # type: ignore[type-arg]
        await _register(factory, tenant, *ids)
        async with factory() as first, factory() as second:
            # Pending uploads created before `soon` are all due.
            claimed_first = [i.public_id for i in await SqlAlchemyImageUploads(first).claim_due(soon, soon, limit=2)]
            claimed_second = [i.public_id for i in await SqlAlchemyImageUploads(second).claim_due(soon, soon, limit=10)]
            await first.rollback()
            await second.rollback()
        return claimed_first, claimed_second

    first, second = asyncio.run(_with_factory(work))

    assert len(first) == 2
    assert set(first).isdisjoint(second)
    assert sorted(first + second) == sorted(ids)


def test_attached_images_are_never_due_and_discarded_ones_always_are(tenant: SeedResult) -> None:
    used, dropped, other_tenant_attempt = (f"tenants/{tenant.tenant_id}/items/{name}" for name in ("used", "dropped", "x"))
    long_ago = datetime.now(UTC) - timedelta(days=1)

    async def work(factory: async_sessionmaker) -> list[str]:  # type: ignore[type-arg]
        await _register(factory, tenant, used, dropped, other_tenant_attempt)
        async with factory() as session:
            uploads = SqlAlchemyImageUploads(session)
            assert await uploads.attach(tenant.tenant_id, used)
            assert await uploads.attach(tenant.tenant_id, dropped)
            await uploads.discard(tenant.tenant_id, dropped)
            # Another tenant can neither attach nor discard this tenant's upload.
            other = (await _seed("Burger Place", "boss@example.com")).tenant_id
            assert not await uploads.attach(other, other_tenant_attempt)
            await uploads.discard(other, used)
            await session.commit()
        async with factory() as session:
            # `long_ago` as the pending cut-off: only discarded rows are due.
            due = await SqlAlchemyImageUploads(session).claim_due(datetime.now(UTC), long_ago, limit=10)
            await session.rollback()
            return [image.public_id for image in due]

    assert asyncio.run(_with_factory(work)) == [dropped]


def test_a_tenant_with_tracked_images_cannot_be_deleted_silently(tenant: SeedResult) -> None:
    from sqlalchemy import delete
    from sqlalchemy.exc import IntegrityError

    from app.modules.tenants.infrastructure.models import TenantModel

    async def work(factory: async_sessionmaker) -> None:  # type: ignore[type-arg]
        await _register(factory, tenant, f"tenants/{tenant.tenant_id}/items/kept")
        async with factory() as session:
            await session.execute(delete(TenantModel).where(TenantModel.id == tenant.tenant_id))
            await session.commit()

    # Its images must go through the cleanup first; dropping the records would orphan them for good.
    with pytest.raises(IntegrityError):
        asyncio.run(_with_factory(work))
