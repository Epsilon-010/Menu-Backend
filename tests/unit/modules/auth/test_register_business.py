import uuid
from datetime import timedelta

import pytest

from app.modules.auth.application.register_business import ADMIN_NAME, RegisterBusiness
from app.modules.auth.application.session_issuer import SessionIssuer
from app.modules.auth.domain.errors import BusinessIdTaken, TooManyLoginAttempts
from app.modules.staff.application.create_user import CreateUser, LockEmail
from app.modules.staff.application.find_user import FindUserByLogin
from app.modules.staff.domain.errors import EmailAlreadyInUse, InvalidUserData
from app.modules.tenants.application.create_tenant import CreateTenant
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.errors import InvalidTenantData, TenantIdTaken
from app.modules.tenants.domain.tenant import Tenant
from app.shared.domain.principal import Role
from tests.unit.fakes import (
    FakeClock,
    FakeLoginAttemptLimiter,
    FakePasswordHasher,
    FakeUnitOfWork,
    InMemoryRefreshTokenRepository,
    InMemoryTenantRepository,
    InMemoryUserRepository,
)
from tests.unit.modules.auth.test_auth_use_cases import FakeAccessTokens, FakeRefreshCodec

pytestmark = pytest.mark.anyio

EMAIL = "owner@example.com"
PASSWORD = "s3cret-pass"
CLIENT = "203.0.113.7"


class SignUpWorld:
    def __init__(self, blocked_for: int | None = None) -> None:
        self.clock = FakeClock()
        self.hasher = FakePasswordHasher()
        self.limiter = FakeLoginAttemptLimiter(blocked_for)
        self.users = InMemoryUserRepository()
        self.tenants = InMemoryTenantRepository()
        self.refresh_tokens = InMemoryRefreshTokenRepository()
        # Stands for the non-committing unit of work the inner create use cases get in production.
        self.inner_uow = FakeUnitOfWork()
        self.uow = FakeUnitOfWork()

    def register(self) -> RegisterBusiness:
        return RegisterBusiness(
            LockEmail(self.users),
            FindUserByLogin(self.users),
            GetTenant(self.tenants),
            CreateTenant(self.tenants, self.inner_uow),
            CreateUser(self.users, self.hasher, self.inner_uow),
            self.hasher,
            self.limiter,
            SessionIssuer(self.refresh_tokens, FakeRefreshCodec(), FakeAccessTokens(), self.clock),
            self.uow,
        )


@pytest.fixture
def world() -> SignUpWorld:
    return SignUpWorld()


async def test_signs_up_a_business_with_its_admin_and_signs_in_with_one_commit(world: SignUpWorld) -> None:
    session = await world.register().execute(" Owner@Example.com ", PASSWORD, " La Taquería ", CLIENT)

    [tenant] = world.tenants.tenants.values()
    [admin] = world.users.users.values()
    assert tenant.name == "La Taquería"
    assert (admin.tenant_id, admin.email, admin.role, admin.full_name) == (tenant.id, EMAIL, Role.ADMIN, ADMIN_NAME)
    assert ADMIN_NAME == "Admin"
    assert admin.password_hash == f"hashed:{PASSWORD}"
    assert session.role is Role.ADMIN
    assert session.access_token == f"access:{admin.id}:{tenant.id}:admin"
    assert session.refresh_expires_at == world.clock.now() + timedelta(days=7)
    [stored] = world.refresh_tokens.tokens.values()
    assert (stored.user_id, stored.tenant_id) == (admin.id, tenant.id)
    # Only the sign-up's own unit of work commits; the inner use cases get one that does not.
    assert world.uow.commits == 1
    assert world.users.email_locks == [EMAIL]


async def test_the_client_chooses_the_tenant_id(world: SignUpWorld) -> None:
    chosen = uuid.uuid4()

    await world.register().execute(EMAIL, PASSWORD, "La Taquería", CLIENT, chosen)

    assert list(world.tenants.tenants) == [chosen]


async def test_every_attempt_counts_against_the_client_and_none_is_reset(world: SignUpWorld) -> None:
    register = world.register()
    await register.execute(EMAIL, PASSWORD, "La Taquería", CLIENT)
    with pytest.raises(EmailAlreadyInUse):
        await register.execute(EMAIL, PASSWORD, "Other", CLIENT)

    assert world.limiter.acquired == [(f"signup:{CLIENT}", CLIENT)] * 2
    assert world.limiter.succeeded_logins == []


async def test_over_the_limit_nothing_is_created() -> None:
    world = SignUpWorld(blocked_for=60)

    with pytest.raises(TooManyLoginAttempts) as error:
        await world.register().execute(EMAIL, PASSWORD, "La Taquería", CLIENT)

    assert error.value.retry_after == 60
    assert (world.tenants.tenants, world.users.users, world.uow.commits) == ({}, {}, 0)


async def test_an_email_in_use_leaves_nothing_behind(world: SignUpWorld) -> None:
    await world.register().execute(EMAIL, PASSWORD, "La Taquería", CLIENT)
    before = dict(world.tenants.tenants)

    with pytest.raises(EmailAlreadyInUse):
        await world.register().execute("OWNER@example.com", "other-pass-123", "Burger Place", CLIENT)

    # Checked before creating the tenant (the unique index still guards a race, rolling everything back).
    assert world.tenants.tenants == before
    assert len(world.users.users) == 1
    assert world.uow.commits == 1


@pytest.mark.parametrize(
    ("email", "password", "business_name", "error"),
    [
        ("not-an-email", PASSWORD, "La Taquería", InvalidUserData),
        (EMAIL, "short", "La Taquería", InvalidUserData),
        (EMAIL, "x" * 129, "La Taquería", InvalidUserData),
        (EMAIL, PASSWORD, "   ", InvalidTenantData),
        (EMAIL, PASSWORD, "x" * 121, InvalidTenantData),
    ],
)
async def test_invalid_data_is_refused_before_anything_is_written(
    world: SignUpWorld, email: str, password: str, business_name: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await world.register().execute(email, password, business_name, CLIENT)

    assert (world.tenants.tenants, world.users.users, world.uow.commits) == ({}, {}, 0)
    assert world.users.email_locks == []


async def test_repeating_the_same_sign_up_signs_in_to_the_account_already_created(world: SignUpWorld) -> None:
    chosen = uuid.uuid4()
    register = world.register()
    first = await register.execute(EMAIL, PASSWORD, "La Taquería", CLIENT, chosen)

    replay = await register.execute(" OWNER@example.com", PASSWORD, "La Taquería", CLIENT, chosen)

    [admin] = world.users.users.values()
    assert list(world.tenants.tenants) == [chosen]
    assert replay.access_token == first.access_token == f"access:{admin.id}:{chosen}:admin"
    assert replay.refresh_token != first.refresh_token
    assert world.uow.commits == 2


@pytest.mark.parametrize(
    ("email", "password"),
    [("other@example.com", PASSWORD), (EMAIL, "other-pass-123")],
)
async def test_the_same_id_with_other_credentials_is_refused(world: SignUpWorld, email: str, password: str) -> None:
    chosen = uuid.uuid4()
    register = world.register()
    await register.execute(EMAIL, PASSWORD, "La Taquería", CLIENT, chosen)

    with pytest.raises(BusinessIdTaken):
        await register.execute(email, password, "La Taquería", CLIENT, chosen)

    assert len(world.users.users) == 1
    assert world.uow.commits == 1


async def test_an_id_of_another_business_is_refused_even_with_its_own_admin_credentials(world: SignUpWorld) -> None:
    first = uuid.uuid4()
    await world.register().execute(EMAIL, PASSWORD, "La Taquería", CLIENT, first)
    second = uuid.uuid4()
    await world.register().execute("boss@example.com", PASSWORD, "Burger Place", CLIENT, second)

    # Admin of the first business replaying with the second business's id.
    with pytest.raises(BusinessIdTaken):
        await world.register().execute(EMAIL, PASSWORD, "La Taquería", CLIENT, second)


async def test_a_replay_for_a_deactivated_admin_is_refused(world: SignUpWorld) -> None:
    from dataclasses import replace

    chosen = uuid.uuid4()
    await world.register().execute(EMAIL, PASSWORD, "La Taquería", CLIENT, chosen)
    [admin] = world.users.users.values()
    world.users.users[admin.id] = replace(admin, is_active=False)

    with pytest.raises(BusinessIdTaken):
        await world.register().execute(EMAIL, PASSWORD, "La Taquería", CLIENT, chosen)


async def test_create_tenant_accepts_a_chosen_id_and_refuses_one_in_use() -> None:
    tenants, uow = InMemoryTenantRepository(), FakeUnitOfWork()
    chosen = uuid.uuid4()

    tenant = await CreateTenant(tenants, uow).execute("La Taquería", chosen)

    assert tenant == Tenant(name="La Taquería", id=chosen)
    with pytest.raises(TenantIdTaken):
        await CreateTenant(tenants, uow).execute("Burger Place", chosen)
