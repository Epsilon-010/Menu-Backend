import asyncio
from dataclasses import replace

from app.modules.staff.infrastructure.repository import SqlAlchemyUserRepository
from app.modules.tables.domain.table import Table
from app.modules.tables.infrastructure.repository import SqlAlchemyTableRepository
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import _seed


async def _write_versions_out_of_order(tenant: SeedResult) -> tuple[int, int]:
    """Stores version 3, then writes back a copy still holding version 2 (a stale read)."""
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            users, tables = SqlAlchemyUserRepository(session), SqlAlchemyTableRepository(session)
            user = await users.get(tenant.tenant_id, tenant.user_id)
            assert user is not None
            table = Table.create(tenant.tenant_id, "Mesa 9", "SV9TBL", "pin-hash")
            await tables.add(table)
            for version in (3, 2):
                await users.update(replace(user, session_version=version))
                await tables.update(replace(table, session_version=version))
            await session.commit()

        async with create_session_factory(engine)() as session:
            stored_user = await SqlAlchemyUserRepository(session).get(tenant.tenant_id, tenant.user_id)
            stored_table = await SqlAlchemyTableRepository(session).get(tenant.tenant_id, table.id)
            assert stored_user is not None and stored_table is not None
            return stored_user.session_version, stored_table.session_version
    finally:
        await engine.dispose()


def test_a_stale_write_never_lowers_a_session_version() -> None:
    # Lowering it would bring back the tokens a credential change ended.
    tenant = asyncio.run(_seed("La Taquería", "owner@example.com"))

    assert asyncio.run(_write_versions_out_of_order(tenant)) == (3, 3)
