import uuid
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.modules.auth.application.get_current_account import GetCurrentAccount
from app.modules.auth.application.login import Login
from app.modules.auth.application.logout import Logout
from app.modules.auth.application.refresh_session import RefreshSession
from app.modules.auth.application.revoke_user_sessions import RevokeTableSessions, RevokeUserSessions
from app.modules.auth.application.session_issuer import SessionIssuer
from app.modules.auth.application.table_login import TableLogin
from app.modules.auth.domain.errors import AccountNotFound, InvalidCredentials, InvalidRefreshToken, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import IssuedAccessToken
from app.modules.staff.application.find_user import FindUserByLogin, GetUser
from app.modules.staff.domain.user import User
from app.modules.tables.application.find_table import FindTableByCode, GetTable
from app.modules.tables.domain.table import Table
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
    InMemoryTableRepository,
    InMemoryTenantRepository,
    InMemoryUserRepository,
)

pytestmark = pytest.mark.anyio

PASSWORD = "s3cret-pass"
PIN = "482913"
CLIENT = "203.0.113.7"


class FakeAccessTokens:
    def issue(
        self,
        subject_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: Role,
        now: datetime,
        *,
        session_version: int,
        table_id: uuid.UUID | None = None,
    ) -> IssuedAccessToken:
        token = f"access:{subject_id}:{tenant_id}:{role}" + (f":{table_id}" if table_id is not None else "")
        if session_version != 1:
            token += f":v{session_version}"
        return IssuedAccessToken(token=token, expires_at=now + timedelta(minutes=15))


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
        self.tables = InMemoryTableRepository()
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

    async def add_table(self, tenant: Tenant, name: str = "Mesa 4", code: str = "K7M2QX", active: bool = True) -> Table:
        await self.tenants.add(tenant)
        table = Table.create(tenant.id, name, code, await self.hasher.hash(PIN))
        table = replace(table, is_active=active)
        await self.tables.add(table)
        return table

    def login(self) -> Login:
        return Login(FindUserByLogin(self.users), self.hasher, self.limiter, self.sessions, self.uow)

    def table_login(self) -> TableLogin:
        return TableLogin(FindTableByCode(self.tables), self.hasher, self.limiter, self.sessions, self.uow)

    def revoke_user_sessions(self) -> RevokeUserSessions:
        return RevokeUserSessions(self.refresh_tokens, self.access_revocations, self.clock)

    def revoke_table_sessions(self) -> RevokeTableSessions:
        return RevokeTableSessions(self.refresh_tokens, self.access_revocations, self.clock)

    def refresh(self) -> RefreshSession:
        return RefreshSession(
            self.refresh_tokens,
            self.codec,
            GetUser(self.users),
            GetTable(self.tables),
            self.sessions,
            self.clock,
            self.uow,
        )

    def logout(self) -> Logout:
        return Logout(self.refresh_tokens, self.codec, self.clock, self.uow)

    def current_account(self) -> GetCurrentAccount:
        return GetCurrentAccount(GetUser(self.users), GetTable(self.tables), GetTenant(self.tenants))


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
async def admin(world: World) -> User:
    return await world.add_user(Tenant(name="La Taquería"), "owner@example.com")


# --- Login -------------------------------------------------------------------------------------


async def test_login_issues_an_access_token_and_a_stored_refresh_token(world: World, admin: User) -> None:
    session = await world.login().execute(" Owner@Example.com ", PASSWORD, CLIENT)

    assert session.role is Role.ADMIN
    assert session.access_token == f"access:{admin.id}:{admin.tenant_id}:admin"
    assert session.access_expires_at == world.clock.now() + timedelta(minutes=15)
    assert session.refresh_token == "refresh-1"
    assert session.refresh_expires_at == world.clock.now() + timedelta(days=7)
    [stored] = world.refresh_tokens.tokens.values()
    assert stored.token_hash == "hash:refresh-1"
    assert (stored.user_id, stored.tenant_id) == (admin.id, admin.tenant_id)
    assert stored.rotated_at is None and stored.revoked_at is None
    assert world.limiter.acquired == [("staff:owner@example.com", CLIENT)]
    assert world.limiter.succeeded_logins == [("staff:owner@example.com", CLIENT)]
    assert world.uow.commits == 1


async def test_staff_member_logs_in_with_their_username_and_gets_a_shift_long_session(world: World) -> None:
    waiter = await world.add_staff(Tenant(name="Burger Place"), "juan.burger")

    session = await world.login().execute(" Juan.Burger ", PASSWORD, CLIENT)

    assert session.role is Role.WAITER
    assert session.access_token == f"access:{waiter.id}:{waiter.tenant_id}:waiter"
    assert session.refresh_expires_at == world.clock.now() + timedelta(hours=12)
    assert world.limiter.acquired == [("staff:juan.burger", CLIENT)]
    assert world.limiter.succeeded_logins == [("staff:juan.burger", CLIENT)]


async def test_login_with_an_unknown_username_fails_generically(world: World) -> None:
    with pytest.raises(InvalidCredentials):
        await world.login().execute("nobody", PASSWORD, CLIENT)

    assert world.hasher.verified == ["dummy"]


async def test_login_with_a_wrong_password_fails_generically_and_keeps_the_attempt_counted(world: World, admin: User) -> None:
    with pytest.raises(InvalidCredentials):
        await world.login().execute("owner@example.com", "wrong-pass", CLIENT)

    assert world.limiter.acquired == [("staff:owner@example.com", CLIENT)]
    assert world.limiter.succeeded_logins == []
    assert world.refresh_tokens.tokens == {}
    assert world.uow.commits == 0


async def test_login_with_an_unknown_email_fails_the_same_way_and_still_spends_a_hash(world: World) -> None:
    with pytest.raises(InvalidCredentials):
        await world.login().execute("Nobody@example.com", PASSWORD, CLIENT)

    assert world.hasher.verified == ["dummy"]
    assert world.limiter.acquired == [("staff:nobody@example.com", CLIENT)]
    assert world.limiter.succeeded_logins == []


async def test_login_of_an_inactive_user_fails_generically(world: World) -> None:
    await world.add_user(Tenant(name="Closed"), "gone@example.com", active=False)

    with pytest.raises(InvalidCredentials):
        await world.login().execute("gone@example.com", PASSWORD, CLIENT)

    assert world.refresh_tokens.tokens == {}


async def test_login_is_blocked_while_the_limiter_says_so(world: World, admin: User) -> None:
    world.limiter.blocked_for = 120

    with pytest.raises(TooManyLoginAttempts) as error:
        await world.login().execute("owner@example.com", PASSWORD, CLIENT)

    assert error.value.retry_after == 120
    assert world.hasher.verified == []
    assert world.limiter.succeeded_logins == []


# --- Refresh -----------------------------------------------------------------------------------


async def test_refresh_rotates_the_token_and_invalidates_the_previous_one(world: World, admin: User) -> None:
    first = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
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
    first = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
    second = await world.refresh().execute(first.refresh_token)
    commits_before = world.uow.commits

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(first.refresh_token)

    assert world.uow.commits == commits_before + 1
    assert all(token.revoked_at is not None for token in world.refresh_tokens.tokens.values())
    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(second.refresh_token)


async def test_reuse_does_not_touch_other_families(world: World, admin: User) -> None:
    stolen = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
    other_device = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
    await world.refresh().execute(stolen.refresh_token)

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(stolen.refresh_token)

    assert (await world.refresh().execute(other_device.refresh_token)).refresh_token


async def test_refresh_rejects_an_expired_token(world: World, admin: User) -> None:
    session = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
    world.clock.advance(timedelta(days=7))

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(session.refresh_token)


@pytest.mark.parametrize("token", ["", "never-issued"])
async def test_refresh_rejects_missing_or_unknown_tokens(world: World, token: str) -> None:
    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(token)


async def test_refresh_of_a_deactivated_user_fails_and_revokes_the_family(world: World, admin: User) -> None:
    session = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
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

    session = await world.login().execute("staff@example.com", PASSWORD, CLIENT)

    assert session.refresh_expires_at == world.clock.now() + ttl


# --- Logout ------------------------------------------------------------------------------------


async def test_logout_revokes_the_family_of_the_presented_token(world: World, admin: User) -> None:
    first = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
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


async def test_revoking_a_user_ends_all_their_refresh_tokens(world: World) -> None:
    tenant = Tenant(name="Burger Place")
    waiter = await world.add_staff(tenant, "juan.burger")
    colleague = await world.add_staff(tenant, "luis.burger")
    tablet = await world.login().execute("juan.burger", PASSWORD, CLIENT)
    phone = await world.login().execute("juan.burger", PASSWORD, CLIENT)
    other = await world.login().execute("luis.burger", PASSWORD, CLIENT)
    commits = world.uow.commits

    await world.revoke_user_sessions().execute(waiter.tenant_id, waiter.id)

    # The calling use case owns the transaction.
    assert world.uow.commits == commits
    for session in (tablet, phone):
        with pytest.raises(InvalidRefreshToken):
            await world.refresh().execute(session.refresh_token)
    assert (await world.refresh().execute(other.refresh_token)).role is Role.WAITER
    assert colleague.id not in world.access_revocations.required


async def test_ending_access_requires_the_new_session_version_and_never_lowers_it(world: World) -> None:
    waiter = await world.add_staff(Tenant(name="Burger Place"), "juan.burger")
    table = await world.add_table(Tenant(name="Burger Place"))

    await world.revoke_user_sessions().end_access(waiter.id, 3)
    await world.revoke_user_sessions().end_access(waiter.id, 2)
    await world.revoke_table_sessions().end_access(table.id, 2)

    assert world.access_revocations.required == {waiter.id: 3, table.id: 2}


async def test_revoking_never_touches_another_tenant(world: World) -> None:
    waiter = await world.add_staff(Tenant(name="Burger Place"), "juan.burger")
    session = await world.login().execute("juan.burger", PASSWORD, CLIENT)

    await world.revoke_user_sessions().execute(uuid.uuid4(), waiter.id)

    assert (await world.refresh().execute(session.refresh_token)).role is Role.WAITER


# --- Current account ---------------------------------------------------------------------------


async def test_current_account_returns_the_user_and_its_tenant(world: World, admin: User) -> None:
    account = await world.current_account().execute(Principal(admin.id, admin.tenant_id, Role.ADMIN))

    assert account.user == admin
    assert account.table is None
    assert account.tenant.name == "La Taquería"


async def test_current_account_never_crosses_tenants(world: World, admin: User) -> None:
    other = await world.add_user(Tenant(name="Other Diner"), "other@example.com")

    with pytest.raises(AccountNotFound):
        await world.current_account().execute(Principal(admin.id, other.tenant_id, Role.ADMIN))


# --- Table devices -----------------------------------------------------------------------------


@pytest.fixture
async def table(world: World) -> Table:
    return await world.add_table(Tenant(name="La Taquería"))


async def test_table_logs_in_with_code_and_pin_and_gets_a_30_day_session_bound_to_the_table(
    world: World, table: Table
) -> None:
    session = await world.table_login().execute(" k7m2qx ", PIN, CLIENT)

    assert session.role is Role.TABLE
    assert session.access_token == f"access:{table.id}:{table.tenant_id}:table:{table.id}"
    assert session.refresh_expires_at == world.clock.now() + timedelta(days=30)
    [stored] = world.refresh_tokens.tokens.values()
    assert (stored.table_id, stored.user_id, stored.tenant_id) == (table.id, None, table.tenant_id)
    assert world.limiter.acquired == [("table:K7M2QX", CLIENT)]
    assert world.limiter.succeeded_logins == [("table:K7M2QX", CLIENT)]
    assert world.uow.commits == 1


async def test_table_login_with_a_wrong_pin_fails_generically(world: World, table: Table) -> None:
    with pytest.raises(InvalidCredentials):
        await world.table_login().execute("K7M2QX", "000000", CLIENT)

    assert world.limiter.succeeded_logins == []
    assert world.refresh_tokens.tokens == {}
    assert world.uow.commits == 0


async def test_table_login_with_an_unknown_code_still_spends_a_hash(world: World) -> None:
    with pytest.raises(InvalidCredentials):
        await world.table_login().execute("NOPE22", PIN, CLIENT)

    assert world.hasher.verified == ["dummy"]
    assert world.limiter.acquired == [("table:NOPE22", CLIENT)]


async def test_inactive_tables_cannot_log_in(world: World) -> None:
    await world.add_table(Tenant(name="Closed"), active=False)

    with pytest.raises(InvalidCredentials):
        await world.table_login().execute("K7M2QX", PIN, CLIENT)

    assert world.refresh_tokens.tokens == {}


async def test_table_login_is_blocked_while_the_limiter_says_so(world: World, table: Table) -> None:
    world.limiter.blocked_for = 60

    with pytest.raises(TooManyLoginAttempts):
        await world.table_login().execute("K7M2QX", PIN, CLIENT)

    assert world.hasher.verified == []


async def test_table_refresh_rotates_inside_the_table_family(world: World, table: Table) -> None:
    first = await world.table_login().execute("K7M2QX", PIN, CLIENT)
    world.clock.advance(timedelta(days=1))

    second = await world.refresh().execute(first.refresh_token)

    assert second.role is Role.TABLE
    assert second.access_token == f"access:{table.id}:{table.tenant_id}:table:{table.id}"
    assert second.refresh_expires_at == world.clock.now() + timedelta(days=30)
    new = await world.refresh_tokens.get_by_hash(f"hash:{second.refresh_token}")
    assert new is not None and new.table_id == table.id and new.user_id is None


async def test_refresh_of_a_deactivated_table_fails_and_revokes_the_family(world: World, table: Table) -> None:
    session = await world.table_login().execute("K7M2QX", PIN, CLIENT)
    world.tables.tables[table.id] = replace(table, is_active=False)

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(session.refresh_token)

    assert all(token.revoked_at is not None for token in world.refresh_tokens.tokens.values())


async def test_revoking_a_table_ends_its_sessions_but_not_the_staff_ones(world: World, table: Table) -> None:
    tablet = await world.table_login().execute("K7M2QX", PIN, CLIENT)
    waiter = await world.add_staff(Tenant(name="La Taquería"), "juan.taco")
    shift = await world.login().execute("juan.taco", PASSWORD, CLIENT)
    commits = world.uow.commits

    await world.revoke_table_sessions().execute(table.tenant_id, table.id)

    assert world.uow.commits == commits
    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(tablet.refresh_token)
    assert (await world.refresh().execute(shift.refresh_token)).role is Role.WAITER
    assert waiter.id not in world.access_revocations.required


async def test_revoking_a_table_never_touches_another_tenant(world: World, table: Table) -> None:
    tablet = await world.table_login().execute("K7M2QX", PIN, CLIENT)

    await world.revoke_table_sessions().execute(uuid.uuid4(), table.id)

    assert (await world.refresh().execute(tablet.refresh_token)).role is Role.TABLE


async def test_current_account_of_a_table_returns_the_table_and_its_tenant(world: World, table: Table) -> None:
    account = await world.current_account().execute(Principal(table.id, table.tenant_id, Role.TABLE, table.id))

    assert account.user is None
    assert account.table == table
    assert account.tenant.name == "La Taquería"


async def test_current_account_of_a_table_never_crosses_tenants_and_rejects_inactive_tables(
    world: World, table: Table
) -> None:
    other = await world.add_table(Tenant(name="Other Diner"), code="OTHER2")

    with pytest.raises(AccountNotFound):
        await world.current_account().execute(Principal(table.id, other.tenant_id, Role.TABLE, table.id))
    world.tables.tables[table.id] = replace(table, is_active=False)
    with pytest.raises(AccountNotFound):
        await world.current_account().execute(Principal(table.id, table.tenant_id, Role.TABLE, table.id))


async def test_staff_and_table_login_attempts_are_counted_apart(world: World) -> None:
    # A staff login typed as "table:<code>" must never count against (and lock out) that table.
    with pytest.raises(InvalidCredentials):
        await world.login().execute("table:K7M2QX", PASSWORD, CLIENT)

    assert world.limiter.acquired == [("staff:table:k7m2qx", CLIENT)]


# --- Session versions (credential changes) -----------------------------------------------------


async def test_a_table_refresh_token_of_an_older_session_version_is_rejected_and_ends_its_family(
    world: World, table: Table
) -> None:
    # A refresh in flight while the PIN changes can store a token the revocation never saw: its version gives it away.
    session = await world.table_login().execute(table.code, PIN, CLIENT)
    await world.tables.update(table.with_sessions_ended())

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(session.refresh_token)

    assert all(token.revoked_at is not None for token in world.refresh_tokens.tokens.values())


async def test_a_staff_refresh_token_of_an_older_session_version_is_rejected_and_ends_its_family(
    world: World, admin: User
) -> None:
    session = await world.login().execute("owner@example.com", PASSWORD, CLIENT)
    await world.users.update(admin.with_sessions_ended())

    with pytest.raises(InvalidRefreshToken):
        await world.refresh().execute(session.refresh_token)

    assert all(token.revoked_at is not None for token in world.refresh_tokens.tokens.values())


async def test_new_sessions_carry_the_current_session_version(world: World, table: Table, admin: User) -> None:
    await world.tables.update(table.with_sessions_ended())
    await world.users.update(admin.with_sessions_ended().with_sessions_ended())

    tablet = await world.refresh().execute((await world.table_login().execute(table.code, PIN, CLIENT)).refresh_token)
    owner = await world.refresh().execute((await world.login().execute("owner@example.com", PASSWORD, CLIENT)).refresh_token)

    assert tablet.access_token.endswith(":v2")
    assert owner.access_token.endswith(":v3")
    versions = {(token.table_id or token.user_id, token.session_version) for token in world.refresh_tokens.tokens.values()}
    assert versions == {(table.id, 2), (admin.id, 3)}


async def test_current_account_rejects_a_token_of_an_older_session_version(
    world: World, table: Table, admin: User
) -> None:
    await world.tables.update(table.with_sessions_ended())
    await world.users.update(admin.with_sessions_ended())

    for stale in (
        Principal(table.id, table.tenant_id, Role.TABLE, table.id, session_version=1),
        Principal(admin.id, admin.tenant_id, Role.ADMIN, session_version=1),
    ):
        with pytest.raises(AccountNotFound):
            await world.current_account().execute(stale)
    current = Principal(table.id, table.tenant_id, Role.TABLE, table.id, session_version=2)
    assert (await world.current_account().execute(current)).table == world.tables.tables[table.id]
