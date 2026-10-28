"""A table code taken by a concurrent create is redrawn inside the same transaction (savepoint)."""

import asyncio

from app.modules.tables.application.manage_tables import CreateTable
from app.modules.tables.domain.table import Table
from app.modules.tables.infrastructure.repository import SqlAlchemyTableRepository
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import _seed
from tests.unit.fakes import FakePasswordHasher, FakeTableCredentials


class BlindToCodes(SqlAlchemyTableRepository):
    """Plays the race: the code check misses the row another request just inserted."""

    async def get_by_code(self, code: str) -> Table | None:
        return None


def test_a_colliding_code_is_redrawn_instead_of_a_500() -> None:
    tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))

    async def work() -> tuple[str, str, list[str]]:
        engine = create_engine(get_settings().database_url)
        try:
            factory = create_session_factory(engine)
            credentials = FakeTableCredentials(["SAME22", "SAME22", "OTHR33"])
            async with factory() as session:
                first = await CreateTable(
                    BlindToCodes(session), credentials, FakePasswordHasher(), SqlAlchemyUnitOfWork(session)
                ).execute(tenant.tenant_id, "Mesa 1")
            async with factory() as session:
                second = await CreateTable(
                    BlindToCodes(session), credentials, FakePasswordHasher(), SqlAlchemyUnitOfWork(session)
                ).execute(tenant.tenant_id, "Mesa 2")
            async with factory() as session:
                stored = [table.code for table in await SqlAlchemyTableRepository(session).list(tenant.tenant_id)]
            return first.table.code, second.table.code, stored
        finally:
            await engine.dispose()

    first, second, stored = asyncio.run(work())

    assert (first, second) == ("SAME22", "OTHR33")
    assert sorted(stored) == ["OTHR33", "SAME22"]
