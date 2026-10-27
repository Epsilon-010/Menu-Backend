import uuid
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.modules.auth.application.get_current_account import GetCurrentAccount
from app.modules.auth.application.login import Login
from app.modules.auth.application.logout import Logout
from app.modules.auth.application.refresh_session import RefreshSession
from app.modules.auth.application.revoke_user_sessions import RevokeUserSessions
from app.modules.auth.application.session_issuer import SessionIssuer
from app.modules.auth.domain.errors import AccountNotFound, InvalidCredentials, InvalidRefreshToken, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import IssuedAccessToken
from app.modules.staff.application.find_user import FindUserByLogin, GetUser
from app.modules.staff.domain.user import User
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.tenant import Tenant
from app.shared.domain.principal import Principal, Role
from tests.unit.fakes import (
    FakeAccessRevocations,
    FakeClock,
    FakeLoginAttemptLimiter,
    FakePasswordHasher,
    FakeUnitOfWork,
    InMemoryRefreshTokenRepository,
    InMemoryTenantRepository,
    InMemoryUserRepository,
)

pytestmark = pytest.mark.anyio

PASSWORD = "s3cret-pass"


class FakeAccessTokens:
    def issue(self, subject_id: uuid.UUID, tenant_id: uuid.UUID, role: Role, now: datetime) -> IssuedAccessToken:
        return IssuedAccessToken(token=f"access:{subject_id}:{tenant_id}:{role}", expires_at=now + timedelta(minutes=15))


class FakeRefreshCodec:
    def __init__(self) -> None:
        self.issued = 0

    def generate(self) -> str:
        self.issued += 1
        return f"refresh-{self.issued}"

    def hash(self, token: str) -> str:
        return f"hash:{token}"


class World:
    """Wires every use case of the auth module to in-memory adapters."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.uow = FakeUnitOfWork()
        self.hasher = FakePasswordHasher()
        self.limiter = FakeLoginAttemptLimiter()
        self.codec = FakeRefreshCodec()
        self.users = InMemoryUserRepository()
        self.tenants = InMemoryTenantRepository()
        self.refresh_tokens = InMemoryRefreshTokenRepository()
        self.access_revocations = FakeAccessRevocations()
        self.sessions = SessionIssuer(self.refresh_tokens, self.codec, FakeAccessTokens(), self.clock)

    async def add_user(self, tenant: Tenant, email: str, role: Role = Role.ADMIN, active: bool = True) -> User:
        await self.tenants.add(tenant)
        user = User(
            tenant_id=tenant.id,
            email=email,
            full_name="Ana Owner",
            role=role,
            password_hash=await self.hasher.hash(PASSWORD),
            is_active=active,
        )
        await self.users.add(user)
        return user

    async def add_staff(self, tenant: Tenant, username: str, role: Role = Role.WAITER) -> User:
        await self.tenants.add(tenant)
        user = User.create_staff(tenant.id, username, "Juan Waiter", role, await self.hasher.hash(PASSWORD))
        await self.users.add(user)
        return user

    def login(self) -> Login:
        return Login(FindUserByLogin(self.users), self.hasher, self.limiter, self.sessions, self.uow)

    def revoke_user_sessions(self) -> RevokeUserSessions:
        return RevokeUserSessions(self.refresh_tokens, self.access_revocations, self.clock)

    def refresh(self) -> RefreshSession:
        return RefreshSession(self.refresh_tokens, self.codec, GetUser(self.users), self.sessions, self.clock, self.uow)

    def logout(self) -> Logout:
        return Logout(self.refresh_tokens, self.codec, self.clock, self.uow)

    def current_account(self) -> GetCurrentAccount:
        return GetCurrentAccount(GetUser(self.users), GetTenant(self.tenants))


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
async def admin(world: World) -> User:
    return await world.add_user(Tenant(name="La Taquería"), "owner@example.com")


# --- Login -------------------------------------------------------------------------------------


async def test_login_issues_an_access_token_and_a_stored_refresh_token(world: World, admin: User) -> None:
    session = await world.login().execute(" Owner@Example.com ", PASSWORD)

    assert session.role is Role.ADMIN
    assert session.access_token == f"access:{admin.id}:{admin.tenant_id}:admin"
    assert session.access_expires_at == world.clock.now() + timedelta(minutes=15)
    assert session.refresh_token == "refresh-1"
    assert session.refresh_expires_at == world.clock.now() + timedelta(days=7)
    [stored] = world.refresh_tokens.tokens.values()
    assert stored.token_hash == "hash:refresh-1"
    assert (stored.user_id, stored.tenant_id) == (admin.id, admin.tenant_id)
    assert stored.rotated_at is None and stored.revoked_at is None
    assert world.limiter.acquired == ["owner@example.com"]
    assert world.limiter.succeeded_logins == ["owner@example.com"]
    assert world.uow.commits == 1


async def test_staff_member_logs_in_with_their_username_and_gets_a_shift_long_session(world: World) -> None:
    waiter = await world.add_staff(Tenant(name="Burger Place"), "juan.burger")

    session = await world.login().execute(" Juan.Burger ", PASSWORD)

    assert session.role is Role.WAITER
    assert session.access_token == f"access:{waiter.id}:{waiter.tenant_id}:waiter"
    assert session.refresh_expires_at == world.clock.now() + timedelta(hours=12)
    assert world.limiter.acquired == ["juan.burger"]
    assert world.limiter.succeeded_logins == ["juan.burger"]


async def test_login_with_an_unknown_username_fails_generically(world: World) -> None:
    with pytest.raises(InvalidCredentials):
        await world.login().execute("nobody", PASSWORD)

    assert world.hasher.verified == ["dummy"]


async def test_login_with_a_wrong_password_fails_generically_and_keeps_the_attempt_counted(world: World, admin: User) -> None:
    with pytest.raises(InvalidCredentials):
        await world.login().execute("owner@example.com", "wrong-pass")

    assert world.limiter.acquired == ["owner@example.com"]
    assert world.limiter.succeeded_logins == []
    assert world.refresh_tokens.tokens == {}
    assert world.uow.commits == 0


async def test_login_with_an_unknown_email_fails_the_same_way_and_still_spends_a_hash(world: World) -> None:
    with pytest.raises(InvalidCredentials):
        await world.login().execute("Nobody@example.com", PASSWORD)

    assert world.hasher.verified == ["dummy"]
    assert world.limiter.acquired == ["nobody@example.com"]
    assert world.limiter.succeeded_logins == []


async def test_login_of_an_inactive_user_fails_generically(world: World) -> None:
    await world.add_user(Tenant(name="Closed"), "gone@example.com", active=False)

    with pytest.raises(InvalidCredentials):
        await world.login().execute("gone@example.com", PASSWORD)

    assert world.refresh_tokens.tokens == {}


async def test_login_is_blocked_while_the_limiter_says_so(world: World, admin: User) -> None:
    world.limiter.blocked_for = 120

    with pytest.raises(TooManyLoginAttempts) as error:
        await world.login().execute("owner@example.com", PASSWORD)

    assert error.value.retry_after == 120
    assert world.hasher.verified == []
    assert world.limiter.succeeded_logins == []


# --- Refresh -----------------------------------------------------------------------------------


async def test_refresh_rotates_the_token_and_invalidates_the_previous_one(world: World, admin: User) -> None:
    first = await world.login().execute("owner@example.com", PASSWORD)
    world.clock.advance(timedelta(hours=1))

    second = await world.refresh().execute(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    assert second.refresh_expires_at == world.clock.now() + timedelta(days=7)
    assert second.access_token == f"access:{admin.id}:{admin.tenant_id}:admin"
    old = await world.refresh_tokens.get_by_hash(f"hash:{first.refresh_token}")
    new = await world.refresh_tokens.get_by_hash(f"hash:{second.refresh_token}")
    assert old is not None and new is not None
    assert old.rotated_at == world.clock.now()
    assert new.family_id == old.family_id
    assert new.rotated_at is None and new.revoked_at is None


async def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(world: World, admin: User) -> None:
    first = await world.login().execute("owner@example.com", PASSWORD)
    second = await world.refresh().execute(first.refresh_token)
    commits_before = world.uow.commits

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(first.refresh_token)

    assert world.uow.commits == commits_before + 1
    assert all(token.revoked_at is not None for token in world.refresh_tokens.tokens.values())
    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(second.refresh_token)


async def test_reuse_does_not_touch_other_families(world: World, admin: User) -> None:
    stolen = await world.login().execute("owner@example.com", PASSWORD)
    other_device = await world.login().execute("owner@example.com", PASSWORD)
    await world.refresh().execute(stolen.refresh_token)

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(stolen.refresh_token)

    assert (await world.refresh().execute(other_device.refresh_token)).refresh_token


async def test_refresh_rejects_an_expired_token(world: World, admin: User) -> None:
    session = await world.login().execute("owner@example.com", PASSWORD)
    world.clock.advance(timedelta(days=7))

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(session.refresh_token)


@pytest.mark.parametrize("token", ["", "never-issued"])
async def test_refresh_rejects_missing_or_unknown_tokens(world: World, token: str) -> None:
    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(token)


async def test_refresh_of_a_deactivated_user_fails_and_revokes_the_family(world: World, admin: User) -> None:
    session = await world.login().execute("owner@example.com", PASSWORD)
    world.users.users[admin.id] = replace(admin, is_active=False)

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(session.refresh_token)

    assert all(token.revoked_at is not None for token in world.refresh_tokens.tokens.values())


@pytest.mark.parametrize(
    ("role", "ttl"),
    [(Role.WAITER, timedelta(hours=12)), (Role.KITCHEN, timedelta(hours=12)), (Role.ADMIN, timedelta(days=7))],
)
async def test_refresh_lifetime_depends_on_the_role(world: World, role: Role, ttl: timedelta) -> None:
    await world.add_user(Tenant(name="Diner"), "staff@example.com", role=role)

    session = await world.login().execute("staff@example.com", PASSWORD)

    assert session.refresh_expires_at == world.clock.now() + ttl


# --- Logout ------------------------------------------------------------------------------------


async def test_logout_revokes_the_family_of_the_presented_token(world: World, admin: User) -> None:
    first = await world.login().execute("owner@example.com", PASSWORD)
    second = await world.refresh().execute(first.refresh_token)

    await world.logout().execute(second.refresh_token)

    assert all(token.revoked_at is not None for token in world.refresh_tokens.tokens.values())
    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(second.refresh_token)


@pytest.mark.parametrize("token", [None, "", "never-issued"])
async def test_logout_without_a_known_token_is_a_no_op(world: World, token: str | None) -> None:
    await world.logout().execute(token)

    assert world.uow.commits == 0


# --- Revoking every session of a user ---------------------------------------------------------


async def test_revoking_a_user_ends_all_their_sessions_and_marks_their_access_tokens(world: World) -> None:
    tenant = Tenant(name="Burger Place")
    waiter = await world.add_staff(tenant, "juan.burger")
    colleague = await world.add_staff(tenant, "luis.burger")
    tablet = await world.login().execute("juan.burger", PASSWORD)
    phone = await world.login().execute("juan.burger", PASSWORD)
    other = await world.login().execute("luis.burger", PASSWORD)
    commits = world.uow.commits

    await world.revoke_user_sessions().execute(waiter.tenant_id, waiter.id)

    # The calling use case owns the transaction.
    assert world.uow.commits == commits
    assert world.access_revocations.revoked == {waiter.id: world.clock.now()}
    for session in (tablet, phone):
        with pytest.raises(InvalidRefreshToken):
            await world.refresh().execute(session.refresh_token)
    assert (await world.refresh().execute(other.refresh_token)).role is Role.WAITER
    assert colleague.id not in world.access_revocations.revoked


async def test_revoking_never_touches_another_tenant(world: World) -> None:
    waiter = await world.add_staff(Tenant(name="Burger Place"), "juan.burger")
    session = await world.login().execute("juan.burger", PASSWORD)

    await world.revoke_user_sessions().execute(uuid.uuid4(), waiter.id)

    assert (await world.refresh().execute(session.refresh_token)).role is Role.WAITER


# --- Current account ---------------------------------------------------------------------------


async def test_current_account_returns_the_user_and_its_tenant(world: World, admin: User) -> None:
    account = await world.current_account().execute(Principal(admin.id, admin.tenant_id, Role.ADMIN))

    assert account.user == admin
    assert account.tenant.name == "La Taquería"


async def test_current_account_never_crosses_tenants(world: World, admin: User) -> None:
    other = await world.add_user(Tenant(name="Other Diner"), "other@example.com")

    with pytest.raises(AccountNotFound):
        await world.current_account().execute(Principal(admin.id, other.tenant_id, Role.ADMIN))
