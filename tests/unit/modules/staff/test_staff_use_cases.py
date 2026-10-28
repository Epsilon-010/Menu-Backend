import uuid

import pytest

from app.modules.staff.application.create_user import CreateUser
from app.modules.staff.application.find_user import FindUserByLogin, GetUser
from app.modules.staff.application.manage_staff import (
    CreateStaffMember,
    ListStaff,
    ResetStaffPassword,
    UpdateStaffMember,
)
from app.modules.staff.domain.errors import (
    StaffIdTaken,
    EmailAlreadyInUse,
    InvalidUserData,
    StaffMemberNotFound,
    UsernameNotAvailable,
)
from app.modules.staff.domain.user import User
from app.shared.domain.principal import Role
from tests.unit.fakes import FakePasswordHasher, FakeUnitOfWork, InMemoryUserRepository

pytestmark = pytest.mark.anyio

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


def create_user(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> CreateUser:
    return CreateUser(users, FakePasswordHasher(), uow)


async def test_creates_an_admin_with_a_hashed_password_and_normalized_email(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    user = await create_user(users, uow).execute(
        tenant_id=TENANT_A, email="  Owner@Example.COM ", full_name="Ana Owner", role=Role.ADMIN, password="s3cret-pass"
    )

    assert user.email == "owner@example.com"
    assert user.role is Role.ADMIN
    assert user.tenant_id == TENANT_A
    assert user.is_active is True
    assert user.password_hash == "hashed:s3cret-pass"
    assert isinstance(user.id, uuid.UUID)
    assert users.users[user.id] == user
    assert uow.commits == 1


async def test_rejects_an_email_already_in_use_even_in_another_tenant(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    use_case = create_user(users, uow)
    await use_case.execute(TENANT_A, "owner@example.com", "Ana", Role.ADMIN, "s3cret-pass")

    with pytest.raises(EmailAlreadyInUse):
        await use_case.execute(TENANT_B, "OWNER@example.com", "Other", Role.ADMIN, "s3cret-pass")

    assert len(users.users) == 1
    assert uow.commits == 1


@pytest.mark.parametrize(
    ("email", "full_name", "password"),
    [
        ("not-an-email", "Ana", "s3cret-pass"),
        ("owner@example.com", "   ", "s3cret-pass"),
        ("owner@example.com", "Ana", "short"),
    ],
)
async def test_rejects_invalid_user_data(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, email: str, full_name: str, password: str
) -> None:
    with pytest.raises(InvalidUserData):
        await create_user(users, uow).execute(TENANT_A, email, full_name, Role.ADMIN, password)

    assert users.users == {}
    assert uow.commits == 0


async def test_rejects_the_table_role_for_staff_accounts(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    with pytest.raises(InvalidUserData):
        await create_user(users, uow).execute(TENANT_A, "t@example.com", "Table", Role.TABLE, "s3cret-pass")


async def test_finds_a_user_by_email_case_insensitively(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    created = await create_user(users, uow).execute(TENANT_A, "owner@example.com", "Ana", Role.ADMIN, "s3cret-pass")

    assert await FindUserByLogin(users).execute(" OWNER@example.com") == created
    assert await FindUserByLogin(users).execute("nobody@example.com") is None


async def test_get_user_is_scoped_to_the_tenant(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    created = await create_user(users, uow).execute(TENANT_A, "owner@example.com", "Ana", Role.ADMIN, "s3cret-pass")

    assert await GetUser(users).execute(TENANT_A, created.id) == created
    assert await GetUser(users).execute(TENANT_B, created.id) is None


# --- Staff management (admin) ------------------------------------------------------------------


class FakeSessionRevoker:
    def __init__(self) -> None:
        self.revoked: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.access_ended: list[tuple[uuid.UUID, int]] = []

    async def revoke_all(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.revoked.append((tenant_id, user_id))

    async def end_access(self, user_id: uuid.UUID, session_version: int) -> None:
        self.access_ended.append((user_id, session_version))


@pytest.fixture
def sessions() -> FakeSessionRevoker:
    return FakeSessionRevoker()


async def add_waiter(users: InMemoryUserRepository, uow: FakeUnitOfWork, tenant_id: uuid.UUID = TENANT_A) -> User:
    return await CreateStaffMember(users, FakePasswordHasher(), uow).execute(
        tenant_id, "juan.burger", "Juan Pérez", Role.WAITER, "s3cret-pass"
    )


async def test_creates_a_staff_member_with_a_normalized_username(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    member = await CreateStaffMember(users, FakePasswordHasher(), uow).execute(
        TENANT_A, "  Juan.Burger ", " Juan Pérez ", Role.KITCHEN, "s3cret-pass"
    )

    assert member.username == "juan.burger"
    assert member.email is None
    assert member.full_name == "Juan Pérez"
    assert member.role is Role.KITCHEN
    assert member.tenant_id == TENANT_A
    assert member.is_active is True
    assert member.password_hash == "hashed:s3cret-pass"
    assert users.users[member.id] == member
    assert uow.commits == 1


async def test_a_username_is_unique_across_tenants(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    await add_waiter(users, uow, TENANT_A)

    with pytest.raises(UsernameNotAvailable):
        await CreateStaffMember(users, FakePasswordHasher(), uow).execute(
            TENANT_B, "JUAN.burger", "Other Juan", Role.WAITER, "s3cret-pass"
        )

    assert len(users.users) == 1
    assert uow.commits == 1


@pytest.mark.parametrize(
    ("username", "full_name", "role", "password"),
    [
        ("ju", "Juan", Role.WAITER, "s3cret-pass"),
        ("j" * 41, "Juan", Role.WAITER, "s3cret-pass"),
        ("juan@burger", "Juan", Role.WAITER, "s3cret-pass"),
        ("juan perez", "Juan", Role.WAITER, "s3cret-pass"),
        ("juan", "  ", Role.WAITER, "s3cret-pass"),
        ("juan", "Juan", Role.WAITER, "short"),
        ("juan", "Juan", Role.ADMIN, "s3cret-pass"),
        ("juan", "Juan", Role.TABLE, "s3cret-pass"),
    ],
)
async def test_rejects_invalid_staff_member_data(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, username: str, full_name: str, role: Role, password: str
) -> None:
    with pytest.raises(InvalidUserData):
        await CreateStaffMember(users, FakePasswordHasher(), uow).execute(TENANT_A, username, full_name, role, password)

    assert users.users == {}
    assert uow.commits == 0


async def test_finds_a_staff_member_by_username_for_login(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    member = await add_waiter(users, uow)

    assert await FindUserByLogin(users).execute(" Juan.Burger") == member
    assert await FindUserByLogin(users).execute("nobody") is None


async def test_lists_only_the_waiters_and_cooks_of_the_tenant_by_name(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    await create_user(users, uow).execute(TENANT_A, "owner@example.com", "Ana Owner", Role.ADMIN, "s3cret-pass")
    create = CreateStaffMember(users, FakePasswordHasher(), uow)
    zoe = await create.execute(TENANT_A, "zoe", "Zoe", Role.KITCHEN, "s3cret-pass")
    bob = await create.execute(TENANT_A, "bob", "bob", Role.WAITER, "s3cret-pass")
    await create.execute(TENANT_B, "carl", "Carl", Role.WAITER, "s3cret-pass")

    assert await ListStaff(users).execute(TENANT_A) == [bob, zoe]


async def test_updates_name_and_role_and_revokes_sessions_on_role_change(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)

    updated = await UpdateStaffMember(users, sessions, uow).execute(
        TENANT_A, member.id, full_name=" Juan P. ", role=Role.KITCHEN
    )

    assert updated.full_name == "Juan P."
    assert updated.role is Role.KITCHEN
    assert users.users[member.id] == updated
    assert sessions.revoked == [(TENANT_A, member.id)]
    assert uow.commits == 2


async def test_renaming_alone_keeps_the_sessions(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)

    await UpdateStaffMember(users, sessions, uow).execute(TENANT_A, member.id, full_name="Juan P.")

    assert sessions.revoked == []


async def test_deactivating_revokes_every_session_and_reactivating_does_not(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)
    update = UpdateStaffMember(users, sessions, uow)

    deactivated = await update.execute(TENANT_A, member.id, is_active=False)
    reactivated = await update.execute(TENANT_A, member.id, is_active=True)

    assert deactivated.is_active is False
    assert reactivated.is_active is True
    assert sessions.revoked == [(TENANT_A, member.id)]


async def test_rejects_an_invalid_update_without_saving(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)

    with pytest.raises(InvalidUserData):
        await UpdateStaffMember(users, sessions, uow).execute(TENANT_A, member.id, role=Role.ADMIN)

    assert users.users[member.id] == member
    assert sessions.revoked == []
    assert uow.commits == 1


async def test_resets_the_password_and_revokes_every_session(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)

    await ResetStaffPassword(users, FakePasswordHasher(), sessions, uow).execute(TENANT_A, member.id, "new-pass-123")

    assert users.users[member.id].password_hash == "hashed:new-pass-123"
    assert sessions.revoked == [(TENANT_A, member.id)]
    assert uow.commits == 2


async def test_rejects_a_short_new_password(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)

    with pytest.raises(InvalidUserData):
        await ResetStaffPassword(users, FakePasswordHasher(), sessions, uow).execute(TENANT_A, member.id, "short")

    assert users.users[member.id] == member
    assert sessions.revoked == []


async def test_staff_management_never_reaches_another_tenant_nor_an_admin(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow, TENANT_B)
    admin = await create_user(users, uow).execute(TENANT_A, "owner@example.com", "Ana", Role.ADMIN, "s3cret-pass")

    for target in (member.id, admin.id, uuid.uuid4()):
        with pytest.raises(StaffMemberNotFound):
            await UpdateStaffMember(users, sessions, uow).execute(TENANT_A, target, is_active=False)
        with pytest.raises(StaffMemberNotFound):
            await ResetStaffPassword(users, FakePasswordHasher(), sessions, uow).execute(TENANT_A, target, "new-pass-123")

    assert users.users[member.id] == member
    assert users.users[admin.id] == admin
    assert sessions.revoked == []


async def test_every_write_locks_the_member_it_rewrites(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)

    await UpdateStaffMember(users, sessions, uow).execute(TENANT_A, member.id, full_name="Juan P.")
    await ResetStaffPassword(users, FakePasswordHasher(), sessions, uow).execute(TENANT_A, member.id, "n3w-secret-pass")

    assert users.locked == [member.id, member.id]


async def test_repeating_a_staff_create_with_its_id_returns_the_same_member(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    member_id = uuid.uuid4()
    create = CreateStaffMember(users, FakePasswordHasher(), uow)

    first = await create.execute(TENANT_A, "juan.burger", "Juan Pérez", Role.WAITER, "s3cret-pass", member_id)
    replay = await create.execute(TENANT_A, " Juan.Burger ", "Juan Pérez", Role.WAITER, "s3cret-pass", member_id)

    assert replay == first
    assert first.id == member_id
    assert list(users.users) == [member_id]
    assert uow.commits == 1


async def test_a_staff_id_reused_for_another_member_or_tenant_is_refused(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    member_id = uuid.uuid4()
    create = CreateStaffMember(users, FakePasswordHasher(), uow)
    await create.execute(TENANT_A, "juan.burger", "Juan Pérez", Role.WAITER, "s3cret-pass", member_id)

    with pytest.raises(StaffIdTaken):
        await create.execute(TENANT_A, "ana.cocina", "Ana", Role.KITCHEN, "s3cret-pass", member_id)
    with pytest.raises(StaffIdTaken):
        await create.execute(TENANT_B, "juan.burger", "Juan Pérez", Role.WAITER, "s3cret-pass", member_id)

    assert [u.username for u in users.users.values()] == ["juan.burger"]


async def test_a_staff_replay_with_another_password_is_refused(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    member_id = uuid.uuid4()
    create = CreateStaffMember(users, FakePasswordHasher(), uow)
    await create.execute(TENANT_A, "juan.burger", "Juan Pérez", Role.WAITER, "first-pass-123", member_id)

    # Same id, same names, other password: not the same request, so it must not succeed silently.
    with pytest.raises(StaffIdTaken):
        await create.execute(TENANT_A, "juan.burger", "Juan Pérez", Role.WAITER, "second-pass-456", member_id)

    assert users.users[member_id].password_hash == "hashed:first-pass-123"


async def test_staff_creates_of_a_tenant_are_serialized(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    await CreateStaffMember(users, FakePasswordHasher(), uow).execute(
        TENANT_A, "juan.burger", "Juan Pérez", Role.WAITER, "s3cret-pass", uuid.uuid4()
    )

    # Taken before the replay check, so a concurrent replay waits and then finds the first one.
    assert users.create_locks == [TENANT_A]


# --- Session versions --------------------------------------------------------------------------


class FailingUnitOfWork(FakeUnitOfWork):
    async def commit(self) -> None:
        raise RuntimeError("commit failed")


async def test_password_reset_role_change_and_deactivation_bump_the_session_version_and_end_access(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)
    update = UpdateStaffMember(users, sessions, uow)

    await ResetStaffPassword(users, FakePasswordHasher(), sessions, uow).execute(TENANT_A, member.id, "new-pass-123")
    await update.execute(TENANT_A, member.id, full_name="Juan P.")
    await update.execute(TENANT_A, member.id, role=Role.KITCHEN)
    await update.execute(TENANT_A, member.id, is_active=False)
    await update.execute(TENANT_A, member.id, is_active=True)

    assert users.users[member.id].session_version == 4
    assert sessions.access_ended == [(member.id, 2), (member.id, 3), (member.id, 4)]


async def test_staff_access_is_only_ended_once_the_new_session_version_is_committed(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, sessions: FakeSessionRevoker
) -> None:
    member = await add_waiter(users, uow)
    failing = FailingUnitOfWork()

    with pytest.raises(RuntimeError):
        await ResetStaffPassword(users, FakePasswordHasher(), sessions, failing).execute(
            TENANT_A, member.id, "new-pass-123"
        )
    with pytest.raises(RuntimeError):
        await UpdateStaffMember(users, sessions, failing).execute(TENANT_A, member.id, is_active=False)

    assert sessions.access_ended == []
