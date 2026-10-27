import uuid

import pytest

from app.modules.staff.application.create_user import CreateUser
from app.modules.staff.application.find_user import FindUserByEmail, GetUser
from app.modules.staff.domain.errors import EmailAlreadyInUse, InvalidUserData
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

    assert await FindUserByEmail(users).execute(" OWNER@example.com") == created
    assert await FindUserByEmail(users).execute("nobody@example.com") is None


async def test_get_user_is_scoped_to_the_tenant(users: InMemoryUserRepository, uow: FakeUnitOfWork) -> None:
    created = await create_user(users, uow).execute(TENANT_A, "owner@example.com", "Ana", Role.ADMIN, "s3cret-pass")

    assert await GetUser(users).execute(TENANT_A, created.id) == created
    assert await GetUser(users).execute(TENANT_B, created.id) is None
