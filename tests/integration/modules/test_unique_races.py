"""Two concurrent requests can both pass the use case's "is it free?" check; the unique index
then rejects the second insert, and the repository must report the domain error (409), not a 500."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff.domain.errors import EmailAlreadyInUse, UsernameNotAvailable
from app.modules.staff.domain.user import User
from app.modules.staff.infrastructure.repository import SqlAlchemyUserRepository
from app.modules.tables.domain.errors import TableNameNotAvailable
from app.modules.tables.domain.table import Table
from app.modules.tables.infrastructure.repository import SqlAlchemyTableRepository
from app.seed import SeedResult
from app.shared.domain.principal import Role
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import _seed


@pytest.fixture
def tenant() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


def _in_two_sessions(first: Callable[[AsyncSession], Awaitable[None]], second: Callable[[AsyncSession], Awaitable[None]]) -> None:
    async def run() -> None:
        engine = create_engine(get_settings().database_url)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await first(session)
                await session.commit()
            async with factory() as session:
                await second(session)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_a_table_name_taken_meanwhile_is_reported_as_not_available(tenant: SeedResult) -> None:
    async def add(name: str, code: str) -> Callable[[AsyncSession], Awaitable[None]]:
        async def action(session: AsyncSession) -> None:
            await SqlAlchemyTableRepository(session).add(Table.create(tenant.tenant_id, name, code, "hash"))

        return action

    first = asyncio.run(add("Mesa 4", "AAAAAA"))
    second = asyncio.run(add("MESA 4", "BBBBBB"))

    with pytest.raises(TableNameNotAvailable):
        _in_two_sessions(first, second)


def test_renaming_onto_a_name_taken_meanwhile_is_reported_as_not_available(tenant: SeedResult) -> None:
    taken = Table.create(tenant.tenant_id, "Mesa 1", "AAAAAA", "hash")
    other = Table.create(tenant.tenant_id, "Mesa 2", "BBBBBB", "hash")

    async def seed(session: AsyncSession) -> None:
        repository = SqlAlchemyTableRepository(session)
        await repository.add(taken)
        await repository.add(other)

    async def rename(session: AsyncSession) -> None:
        await SqlAlchemyTableRepository(session).update(other.with_changes(name="mesa 1"))

    with pytest.raises(TableNameNotAvailable):
        _in_two_sessions(seed, rename)


@pytest.mark.parametrize(
    ("make_user", "error"),
    [
        (lambda tenant_id: User.create_staff(tenant_id, "juan.taco", "Juan", Role.WAITER, "hash"), UsernameNotAvailable),
        (lambda tenant_id: User.create(tenant_id, "owner@example.com", "Ana", Role.ADMIN, "hash"), EmailAlreadyInUse),
    ],
)
def test_a_login_taken_meanwhile_is_reported_as_not_available(
    tenant: SeedResult, make_user: Callable[..., User], error: type[Exception]
) -> None:
    async def first(session: AsyncSession) -> None:
        if error is UsernameNotAvailable:
            await SqlAlchemyUserRepository(session).add(make_user(tenant.tenant_id))

    async def second(session: AsyncSession) -> None:
        # The seeded admin already owns owner@example.com.
        await SqlAlchemyUserRepository(session).add(make_user(tenant.tenant_id))

    with pytest.raises(error):
        _in_two_sessions(first, second)
