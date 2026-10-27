"""In-memory fakes for the domain ports, shared by the unit tests."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.modules.auth.domain.refresh_token import RefreshToken
from app.modules.staff.domain.user import STAFF_MEMBER_ROLES, User
from app.modules.tenants.domain.tenant import Tenant


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self.now_value = now or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.now_value

    def advance(self, delta: timedelta) -> None:
        self.now_value += delta


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakePasswordHasher:
    """Reversible stand-in for Argon2: keeps tests fast and readable."""

    def __init__(self) -> None:
        self.verified: list[str] = []

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        self.verified.append(password_hash)
        return password_hash == f"hashed:{password}"

    async def verify_dummy(self, password: str) -> None:
        self.verified.append("dummy")


class InMemoryTenantRepository:
    def __init__(self) -> None:
        self.tenants: dict[uuid.UUID, Tenant] = {}

    async def add(self, tenant: Tenant) -> None:
        self.tenants[tenant.id] = tenant

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return self.tenants.get(tenant_id)


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    async def add(self, user: User) -> None:
        self.users[user.id] = user

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        user = self.users.get(user_id)
        return user if user is not None and user.tenant_id == tenant_id else None

    async def get_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def get_by_username(self, username: str) -> User | None:
        return next((user for user in self.users.values() if user.username == username), None)

    async def list_staff(self, tenant_id: uuid.UUID) -> list[User]:
        staff = [user for user in self.users.values() if user.tenant_id == tenant_id and user.role in STAFF_MEMBER_ROLES]
        return sorted(staff, key=lambda user: user.full_name.lower())

    async def update(self, user: User) -> None:
        self.users[user.id] = user


class InMemoryRefreshTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[uuid.UUID, RefreshToken] = {}

    async def add(self, token: RefreshToken) -> None:
        self.tokens[token.id] = token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((token for token in self.tokens.values() if token.token_hash == token_hash), None)

    async def mark_rotated(self, token_id: uuid.UUID, at: datetime) -> bool:
        token = self.tokens[token_id]
        if token.rotated_at is not None or token.revoked_at is not None:
            return False
        self.tokens[token_id] = replace(token, rotated_at=at)
        return True

    async def revoke_family(self, family_id: uuid.UUID, at: datetime) -> None:
        for token_id, token in self.tokens.items():
            if token.family_id == family_id and token.revoked_at is None:
                self.tokens[token_id] = replace(token, revoked_at=at)

    async def revoke_all_for_user(self, tenant_id: uuid.UUID, user_id: uuid.UUID, at: datetime) -> None:
        for token_id, token in self.tokens.items():
            if token.tenant_id == tenant_id and token.user_id == user_id and token.revoked_at is None:
                self.tokens[token_id] = replace(token, revoked_at=at)


class FakeAccessRevocations:
    def __init__(self) -> None:
        self.revoked: dict[uuid.UUID, datetime] = {}

    async def revoke(self, subject_id: uuid.UUID, at: datetime) -> None:
        self.revoked[subject_id] = at

    async def revoked_since(self, subject_id: uuid.UUID) -> datetime | None:
        return self.revoked.get(subject_id)


class FakeLoginAttemptLimiter:
    def __init__(self, blocked_for: int | None = None) -> None:
        self.blocked_for = blocked_for
        self.acquired: list[str] = []
        self.succeeded_logins: list[str] = []

    async def acquire(self, account: str) -> int | None:
        self.acquired.append(account)
        return self.blocked_for

    async def succeeded(self, account: str) -> None:
        self.succeeded_logins.append(account)