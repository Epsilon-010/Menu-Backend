import uuid

import pytest

from app.modules.staff.application.manage_admins import (
    CreateAdmin,
    ListAdmins,
    ReplaceOwnPassword,
    UpdateAdmin,
    check_new_password,
)
from app.modules.staff.domain.errors import (
    AdminAlreadyCreated,
    AdminNotFound,
    CannotDeactivateSelf,
    EmailAlreadyInUse,
    InvalidUserData,
    NotAnActiveAdmin,
    StaffIdTaken,
    WrongCurrentPassword,
)
from app.modules.staff.domain.user import User
from app.shared.domain.principal import Role
from tests.unit.fakes import FakePasswordHasher, FakeStaffCredentials, FakeUnitOfWork, InMemoryUserRepository
from tests.unit.modules.staff.test_staff_use_cases import FakeSessionRevoker

pytestmark = pytest.mark.anyio

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def sessions() -> FakeSessionRevoker:
    return FakeSessionRevoker()


def owner_of(users: InMemoryUserRepository, tenant_id: uuid.UUID = TENANT_A, email: str = "owner@example.com") -> User:
    owner = User.create(tenant_id, email, "Owner", Role.ADMIN, "hashed:owner-pass")
    users.users[owner.id] = owner
    return owner


def create_admin(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> CreateAdmin:
    return CreateAdmin(users, FakeStaffCredentials(), FakePasswordHasher(), uow)


def update_admin(users: InMemoryUserRepository, sessions: FakeSessionRevoker, uow: FakeUnitOfWork) -> UpdateAdmin:
    return UpdateAdmin(users, sessions, uow)


# --- CreateAdmin --------------------------------------------------------------------------------


async def test_creates_an_admin_with_a_hashed_temporary_password(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    result = await create_admin(users, uow).execute(TENANT_A, " Manager ", " Manager@Example.com ")

    admin = result.admin
    assert result.temporary_password == "TEMPPASS0001"
    assert admin.password_hash == "hashed:TEMPPASS0001"
    assert (admin.tenant_id, admin.role, admin.email, admin.full_name) == (
        TENANT_A,
        Role.ADMIN,
        "manager@example.com",
        "Manager",
    )
    assert admin.must_change_password is True
    assert users.users[admin.id] == admin
    assert users.create_locks == [TENANT_A]
    assert uow.commits == 1


async def test_an_email_in_use_in_any_tenant_is_refused(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    owner_of(users, TENANT_B, "boss@example.com")

    with pytest.raises(EmailAlreadyInUse):
        await create_admin(users, uow).execute(TENANT_A, "Manager", "BOSS@example.com")
    assert uow.commits == 0


@pytest.mark.parametrize(("name", "email"), [("", "x@example.com"), ("Manager", "nope")])
async def test_invalid_data_is_refused_before_anything_is_written(
    users: InMemoryUserRepository, uow: FakeUnitOfWork, name: str, email: str
) -> None:
    with pytest.raises(InvalidUserData):
        await create_admin(users, uow).execute(TENANT_A, name, email)
    assert users.users == {}
    assert users.create_locks == []


async def test_a_replay_of_the_same_id_is_reported_without_a_second_admin(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    admin_id = uuid.uuid4()
    await create_admin(users, uow).execute(TENANT_A, "Manager", "manager@example.com", admin_id)

    with pytest.raises(AdminAlreadyCreated):
        await create_admin(users, uow).execute(TENANT_A, "Manager", "manager@example.com", admin_id)
    assert len(users.users) == 1


async def test_an_id_of_another_tenant_or_a_waiter_is_refused(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    other = owner_of(users, TENANT_B, "boss@example.com")
    waiter = User(tenant_id=TENANT_A, full_name="Waiter", role=Role.WAITER, password_hash="x", username="abc234")
    users.users[waiter.id] = waiter

    for clash in (other.id, waiter.id):
        with pytest.raises(StaffIdTaken):
            await create_admin(users, uow).execute(TENANT_A, "Manager", f"{clash.hex[:6]}@example.com", clash)


# --- ListAdmins -----------------------------------------------------------------------------------


async def test_lists_only_the_tenants_admins(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    owner = owner_of(users)
    owner_of(users, TENANT_B, "boss@example.com")
    waiter = User(tenant_id=TENANT_A, full_name="A waiter", role=Role.WAITER, password_hash="x")
    users.users[waiter.id] = waiter

    assert await ListAdmins(users).execute(TENANT_A) == [owner]


# --- UpdateAdmin ----------------------------------------------------------------------------------


async def test_deactivating_an_admin_ends_their_sessions_after_the_commit(
    users: InMemoryUserRepository, sessions: FakeSessionRevoker, uow: FakeUnitOfWork
) -> None:
    owner = owner_of(users)
    manager = (await create_admin(users, uow).execute(TENANT_A, "Manager", "m@example.com")).admin

    updated = await update_admin(users, sessions, uow).execute(TENANT_A, owner.id, manager.id, is_active=False)

    assert updated.is_active is False
    assert updated.session_version == manager.session_version + 1
    assert sessions.revoked == [(TENANT_A, manager.id)]
    assert sessions.access_ended == [(manager.id, updated.session_version)]
    assert users.admin_locks == [TENANT_A]
    assert users.locked == [owner.id, manager.id]


async def test_renaming_or_reactivating_keeps_the_sessions(
    users: InMemoryUserRepository, sessions: FakeSessionRevoker, uow: FakeUnitOfWork
) -> None:
    owner = owner_of(users)
    manager = (await create_admin(users, uow).execute(TENANT_A, "Manager", "m@example.com")).admin

    updated = await update_admin(users, sessions, uow).execute(TENANT_A, owner.id, manager.id, full_name="Boss")

    assert updated.full_name == "Boss"
    assert sessions.revoked == []


async def test_nobody_deactivates_themselves(
    users: InMemoryUserRepository, sessions: FakeSessionRevoker, uow: FakeUnitOfWork
) -> None:
    owner = owner_of(users)

    with pytest.raises(CannotDeactivateSelf):
        await update_admin(users, sessions, uow).execute(TENANT_A, owner.id, owner.id, is_active=False)
    assert users.users[owner.id].is_active is True


async def test_an_inactive_caller_cannot_change_anyone(
    users: InMemoryUserRepository, sessions: FakeSessionRevoker, uow: FakeUnitOfWork
) -> None:
    owner = owner_of(users)
    manager = (await create_admin(users, uow).execute(TENANT_A, "Manager", "m@example.com")).admin
    users.users[manager.id] = manager.with_changes(is_active=False)

    with pytest.raises(NotAnActiveAdmin):
        await update_admin(users, sessions, uow).execute(TENANT_A, manager.id, owner.id, is_active=False)
    assert users.users[owner.id].is_active is True


async def test_waiters_and_other_tenants_admins_are_not_found(
    users: InMemoryUserRepository, sessions: FakeSessionRevoker, uow: FakeUnitOfWork
) -> None:
    owner = owner_of(users)
    other = owner_of(users, TENANT_B, "boss@example.com")
    waiter = User(tenant_id=TENANT_A, full_name="Waiter", role=Role.WAITER, password_hash="x")
    users.users[waiter.id] = waiter

    for target in (other.id, waiter.id, uuid.uuid4()):
        with pytest.raises(AdminNotFound):
            await update_admin(users, sessions, uow).execute(TENANT_A, owner.id, target, is_active=False)
    assert users.users[other.id].is_active is True


# --- ReplaceOwnPassword ---------------------------------------------------------------------------


async def test_replacing_the_password_clears_the_temporary_flag_and_bumps_the_session_version(
    users: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    manager = (await create_admin(users, uow).execute(TENANT_A, "Manager", "m@example.com")).admin

    updated = await ReplaceOwnPassword(users, FakePasswordHasher()).execute(
        TENANT_A, manager.id, "TEMPPASS0001", "my-own-pass"
    )

    assert updated.password_hash == "hashed:my-own-pass"
    assert updated.must_change_password is False
    assert updated.session_version == manager.session_version + 1
    assert users.users[manager.id] == updated
    assert users.locked == [manager.id]


async def test_a_wrong_current_password_changes_nothing(users: InMemoryUserRepository) -> None:
    owner = owner_of(users)

    with pytest.raises(WrongCurrentPassword):
        await ReplaceOwnPassword(users, FakePasswordHasher()).execute(TENANT_A, owner.id, "guess", "my-own-pass")
    assert users.users[owner.id] == owner


async def test_only_an_active_admin_of_the_tenant_replaces_a_password(users: InMemoryUserRepository) -> None:
    owner = owner_of(users)

    with pytest.raises(NotAnActiveAdmin):
        await ReplaceOwnPassword(users, FakePasswordHasher()).execute(TENANT_B, owner.id, "owner-pass", "my-own-pass")


@pytest.mark.parametrize(
    ("new", "message"),
    [("short", "Password must have 8 to 128 characters"), ("same-pass", "The new password must be different")],
)
def test_the_new_password_is_checked(new: str, message: str) -> None:
    with pytest.raises(InvalidUserData, match=message):
        check_new_password("same-pass", new)
