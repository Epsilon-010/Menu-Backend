"""Concurrent replays of one create (tables) against real Postgres: never a wrong answer.

The slow repositories pause after the replay lookup, so without the per-tenant create lock the
replays would all miss the first row and fail on its primary key with a misleading 409.
"""

import asyncio
import uuid
from typing import Any

import pytest

from app.modules.tables.application.manage_tables import CreateTable
from app.modules.tables.domain.errors import TableAlreadyCreated
from app.modules.tables.infrastructure.repository import RandomTableCredentials, SqlAlchemyTableRepository
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import _seed
from tests.unit.fakes import FakePasswordHasher

PAUSE = 0.15


class SlowTables(SqlAlchemyTableRepository):
    async def get(self, *args: Any) -> Any:
        found = await super().get(*args)
        await asyncio.sleep(PAUSE)
        return found


@pytest.fixture
def tenant() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


async def _gather(*calls: Any) -> list[Any]:
    return list(await asyncio.gather(*calls, return_exceptions=True))


def test_concurrent_table_replays_create_one_table_and_say_so(tenant: SeedResult) -> None:
    table_id = uuid.uuid4()

    async def work() -> tuple[list[Any], int]:
        engine = create_engine(get_settings().database_url)
        try:
            factory = create_session_factory(engine)

            async def create() -> uuid.UUID:
                async with factory() as session:
                    use_case = CreateTable(
                        SlowTables(session), RandomTableCredentials(), FakePasswordHasher(), SqlAlchemyUnitOfWork(session)
                    )
                    return (await use_case.execute(tenant.tenant_id, "Mesa 7", table_id)).table.id

            results = await _gather(*(create() for _ in range(3)))
            async with factory() as session:
                count = len(await SqlAlchemyTableRepository(session).list(tenant.tenant_id))
            return results, count
        finally:
            await engine.dispose()

    results, count = asyncio.run(work())

    assert results.count(table_id) == 1
    # The others learn the table exists (its PIN was shown once), never "id used by something else".
    assert sorted(type(r).__name__ for r in results if r != table_id) == [TableAlreadyCreated.__name__] * 2
    assert count == 1
