"""Concurrent publishes against real Postgres: each one gets its own history number, none fails.

The slow history pauses right after reading the versions, so without the theme row lock two publishes would read
the same newest number and both write the next one (the unique number would turn one of them into an error).
"""

import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.media.infrastructure.repository import SqlAlchemyImageUploads
from app.modules.theming.application.manage_theme import ListThemeVersions, PublishTheme
from app.modules.theming.infrastructure.repository import SqlAlchemyThemeHistory, SqlAlchemyThemeRepository
from app.seed import SeedResult
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork
from app.shared.infrastructure.security import SystemClock
from tests.integration.modules.auth.test_auth_api import _seed
from tests.integration.modules.catalog.test_catalog_concurrency import PAUSE, _in_session, _run
from tests.unit.fakes import FakeCleanupScheduler, FakePublishedThemeCache


class SlowHistory(SqlAlchemyThemeHistory):
    async def list(self, *args: Any) -> Any:
        found = await super().list(*args)
        await asyncio.sleep(PAUSE)
        return found


@pytest.fixture
def tenant() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


def test_concurrent_publishes_each_add_their_own_version(tenant: SeedResult) -> None:
    async def publish(session: AsyncSession) -> None:
        use_case = PublishTheme(
            SqlAlchemyThemeRepository(session),
            SlowHistory(session),
            SqlAlchemyImageUploads(session),
            SqlAlchemyUnitOfWork(session),
            FakeCleanupScheduler(),
            FakePublishedThemeCache(),
            SystemClock(),
        )
        await use_case.execute(tenant.tenant_id)

    async def work(factory: async_sessionmaker[AsyncSession]) -> list[int]:
        await asyncio.gather(*(_in_session(factory, publish) for _ in range(3)))
        versions = await _in_session(
            factory, lambda s: ListThemeVersions(SqlAlchemyThemeHistory(s)).execute(tenant.tenant_id)
        )
        return [version.number for version in versions]

    assert _run(work) == [3, 2, 1]
