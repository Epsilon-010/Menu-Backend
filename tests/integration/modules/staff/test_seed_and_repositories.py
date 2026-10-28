import asyncio
import uuid

import pytest
from argon2 import PasswordHasher as Argon2

from app.modules.staff.domain.errors import EmailAlreadyInUse
from app.modules.staff.domain.user import User
from app.modules.staff.infrastructure.repository import SqlAlchemyUserRepository
from app.modules.tenants.domain.tenant import Tenant
from app.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository
from app.seed import SeedResult, main, seed_tenant
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from app.shared.infrastructure.security import Argon2PasswordHasher


async def _seed(tenant: str, email: str, password: str = "s3cret-pass") -> SeedResult:
    engine = create_engine(get_settings().database_url)
    try:
        return await seed_tenant(create_session_factory(engine), tenant, email, "Owner", password)
    finally:
        await engine.dispose()


async def _load(tenant_id: uuid.UUID, user_id: uuid.UUID, email: str) -> tuple[Tenant | None, User | None, User | None]:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            users = SqlAlchemyUserRepository(session)
            return (
                await SqlAlchemyTenantRepository(session).get(tenant_id),
                await users.get(tenant_id, user_id),
                await users.get_by_email(email),
            )
    finally:
        await engine.dispose()


def test_seed_creates_a_tenant_and_its_admin_with_an_argon2_hash() -> None:
    result = asyncio.run(_seed("La Taquería", "Owner@Example.com"))

    tenant, user, by_email = asyncio.run(_load(result.tenant_id, result.user_id, "owner@example.com"))

    assert tenant is not None and user is not None
    assert tenant.name == "La Taquería"
    assert user == by_email
    assert user.email == "owner@example.com"
    assert user.role == "admin"
    assert user.password_hash.startswith("$argon2id$")
    assert Argon2().verify(user.password_hash, "s3cret-pass")


def test_seed_refuses_an_email_that_already_exists() -> None:
    asyncio.run(_seed("First", "owner@example.com"))

    with pytest.raises(EmailAlreadyInUse):
        asyncio.run(_seed("Second", "OWNER@example.com"))


def test_users_are_not_visible_from_another_tenant() -> None:
    a = asyncio.run(_seed("Tenant A", "a@example.com"))
    b = asyncio.run(_seed("Tenant B", "b@example.com"))

    _, user_from_b, _ = asyncio.run(_load(b.tenant_id, a.user_id, "a@example.com"))

    assert user_from_b is None


def test_seed_command_line_creates_the_admin(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--tenant-name", "CLI Diner", "--admin-email", "cli@example.com", "--admin-password", "s3cret-pass"])

    assert exit_code == 0
    assert "cli@example.com" in capsys.readouterr().out


def test_seed_command_line_reports_a_duplicate_email(capsys: pytest.CaptureFixture[str]) -> None:
    asyncio.run(_seed("First", "dup@example.com"))

    exit_code = main(["--tenant-name", "Again", "--admin-email", "dup@example.com", "--admin-password", "s3cret-pass"])

    assert exit_code == 1
    assert "already in use" in capsys.readouterr().err


async def _check_argon2() -> tuple[bool, bool, bool]:
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash("s3cret-pass")
    await hasher.verify_dummy("anything")
    return (
        await hasher.verify(password_hash, "s3cret-pass"),
        await hasher.verify(password_hash, "wrong-pass"),
        await hasher.verify("not-a-hash", "s3cret-pass"),
    )


def test_argon2_hasher_verifies_only_the_right_password() -> None:
    assert asyncio.run(_check_argon2()) == (True, False, False)


async def _code_taken_meanwhile(tenant_id: uuid.UUID) -> tuple[bool, bool]:
    """A concurrent create stored the code first: the insert reports StaffCodeTaken and, thanks to its
    savepoint, the same transaction can still insert the member with another code."""
    from app.modules.staff.domain.errors import StaffCodeTaken
    from app.shared.domain.principal import Role

    engine = create_engine(get_settings().database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            await SqlAlchemyUserRepository(session).add(User.create_staff(tenant_id, "K7M2QX", "Juan", Role.WAITER, "h"))
            await session.commit()
        async with factory() as session:
            users = SqlAlchemyUserRepository(session)
            retry = User.create_staff(tenant_id, "k7m2qx", "Juan", Role.WAITER, "h")
            try:
                await users.add(retry)
                collided = False
            except StaffCodeTaken:
                collided = True
            await users.add(User.create_staff(tenant_id, "P4R5ST", "Juan", Role.WAITER, "h", retry.id))
            await session.commit()
            return collided, await users.get_by_username("p4r5st") is not None
    finally:
        await engine.dispose()


def test_a_staff_code_taken_meanwhile_is_reported_and_the_transaction_goes_on() -> None:
    tenant = asyncio.run(_seed("La Taquería", "owner@example.com"))

    assert asyncio.run(_code_taken_meanwhile(tenant.tenant_id)) == (True, True)


def test_concurrent_staff_replays_create_one_member_and_say_so() -> None:
    """Replaces the old "all get the same member": the PIN is shown once, so the replays learn the
    member exists (StaffAlreadyCreated), never "id used by something else"."""
    from typing import Any

    from app.modules.staff.application.manage_staff import CreateStaffMember
    from app.modules.staff.domain.errors import StaffAlreadyCreated
    from app.modules.staff.infrastructure.repository import RandomStaffCredentials
    from app.shared.domain.principal import Role
    from app.shared.infrastructure.database import SqlAlchemyUnitOfWork
    from tests.unit.fakes import FakePasswordHasher

    class SlowUsers(SqlAlchemyUserRepository):
        async def get(self, *args: Any) -> Any:
            found = await super().get(*args)
            await asyncio.sleep(0.15)
            return found

    tenant = asyncio.run(_seed("La Taquería", "owner@example.com"))
    member_id = uuid.uuid4()

    async def work() -> tuple[list[Any], int]:
        engine = create_engine(get_settings().database_url)
        try:
            factory = create_session_factory(engine)

            async def create() -> uuid.UUID:
                async with factory() as session:
                    use_case = CreateStaffMember(
                        SlowUsers(session), RandomStaffCredentials(), FakePasswordHasher(), SqlAlchemyUnitOfWork(session)
                    )
                    return (await use_case.execute(tenant.tenant_id, "Juan Pérez", Role.WAITER, member_id)).member.id

            results = list(await asyncio.gather(*(create() for _ in range(3)), return_exceptions=True))
            async with factory() as session:
                count = len(await SqlAlchemyUserRepository(session).list_staff(tenant.tenant_id))
            return results, count
        finally:
            await engine.dispose()

    results, count = asyncio.run(work())

    assert results.count(member_id) == 1
    assert sorted(type(r).__name__ for r in results if r != member_id) == [StaffAlreadyCreated.__name__] * 2
    assert count == 1
