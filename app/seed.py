"""Bootstrap command: creates a tenant and its first admin.

Usage (from Backend/):
    uv run python -m app.seed --tenant-name "My Diner" --admin-email owner@example.com
The password is read from --admin-password, the SEED_ADMIN_PASSWORD variable, or a prompt.
"""

import argparse
import asyncio
import getpass
import os
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.staff.application.create_user import CreateUser
from app.modules.staff.application.find_user import FindUserByLogin
from app.modules.staff.domain.errors import EmailAlreadyInUse, InvalidUserData
from app.modules.staff.domain.user import validate_password
from app.modules.staff.infrastructure.repository import SqlAlchemyUserRepository
from app.modules.tenants.application.create_tenant import CreateTenant
from app.modules.tenants.domain.errors import InvalidTenantData
from app.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository
from app.shared.domain.principal import Role
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, create_engine, create_session_factory
from app.shared.infrastructure.security import Argon2PasswordHasher


@dataclass(frozen=True)
class SeedResult:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email: str


async def seed_tenant(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_name: str,
    admin_email: str,
    admin_name: str,
    admin_password: str,
) -> SeedResult:
    async with session_factory() as session:
        users = SqlAlchemyUserRepository(session)
        # Fail before creating the tenant, so a rejected seed leaves nothing behind.
        validate_password(admin_password)
        if await FindUserByLogin(users).execute(admin_email) is not None:
            raise EmailAlreadyInUse(admin_email)

        uow = SqlAlchemyUnitOfWork(session)
        tenant = await CreateTenant(SqlAlchemyTenantRepository(session), uow).execute(tenant_name)
        admin = await CreateUser(users, Argon2PasswordHasher(), uow).execute(
            tenant.id, admin_email, admin_name, Role.ADMIN, admin_password
        )
        return SeedResult(tenant_id=tenant.id, user_id=admin.id, email=admin.email)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description="Create a tenant and its first admin.")
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-name", default="Admin")
    parser.add_argument("--admin-password", help="defaults to $SEED_ADMIN_PASSWORD, then an interactive prompt")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace, password: str) -> SeedResult:
    engine = create_engine(get_settings().database_url)
    try:
        return await seed_tenant(
            create_session_factory(engine), args.tenant_name, args.admin_email, args.admin_name, password
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    password = args.admin_password or os.environ.get("SEED_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    try:
        result = asyncio.run(_run(args, password))
    except EmailAlreadyInUse:
        print(f"Email {args.admin_email} is already in use.", file=sys.stderr)
        return 1
    except (InvalidUserData, InvalidTenantData) as error:
        print(f"Invalid data: {error}", file=sys.stderr)
        return 1
    print(f"Created tenant {result.tenant_id} with admin {result.email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
