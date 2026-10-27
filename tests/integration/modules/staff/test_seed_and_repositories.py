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
