import uuid

from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import BusinessIdTaken, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import LoginAttemptLimiter
from app.modules.staff.application.create_user import CreateUser, LockEmail
from app.modules.staff.application.find_user import FindUserByLogin
from app.modules.staff.domain.errors import EmailAlreadyInUse
from app.modules.staff.domain.user import User, validate_password
from app.modules.tenants.application.create_tenant import CreateTenant
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.tenant import Tenant
from app.shared.domain.ports import PasswordHasher, UnitOfWork
from app.shared.domain.principal import Role

# The sign-up asks for nothing else: the owner can rename the admin later.
ADMIN_NAME = "Admin"


class RegisterBusiness:
    """Self sign-up: creates a business (tenant) and its admin, and signs the admin in.

    One transaction: `create_tenant` and `create_user` must be built with a unit of work that does not
    commit, so the tenant, the admin and the refresh token are committed together here, or nothing is.
    `tenant_id` is chosen by the client to make the sign-up idempotent: repeating it with the same email,
    password and business name signs in to the account already created.
    """

    def __init__(
        self,
        lock_email: LockEmail,
        find_user: FindUserByLogin,
        get_tenant: GetTenant,
        create_tenant: CreateTenant,
        create_user: CreateUser,
        hasher: PasswordHasher,
        limiter: LoginAttemptLimiter,
        sessions: SessionIssuer,
        uow: UnitOfWork,
    ) -> None:
        self._lock_email = lock_email
        self._find_user = find_user
        self._get_tenant = get_tenant
        self._create_tenant = create_tenant
        self._create_user = create_user
        self._hasher = hasher
        self._limiter = limiter
        self._sessions = sessions
        self._uow = uow

    async def execute(
        self, email: str, password: str, business_name: str, client: str, tenant_id: uuid.UUID | None = None
    ) -> AuthSession:
        """`client` is the caller's IP: every attempt counts against it (sign-ups are never "successful
        logins" that reset the counter), so one device cannot create businesses in bulk."""
        attempts_key = f"signup:{client}"
        retry_after = await self._limiter.acquire(attempts_key, client)
        if retry_after is not None:
            raise TooManyLoginAttempts(retry_after)

        # Validate everything before locking, hashing or writing.
        validate_password(password)
        business = Tenant.create(business_name)
        User.create(uuid.uuid4(), email, ADMIN_NAME, Role.ADMIN, password_hash="")

        # Taken before the checks, so a concurrent replay waits for the first sign-up and then finds it.
        await self._lock_email.execute(email)
        if tenant_id is not None and (existing := await self._get_tenant.execute(tenant_id)) is not None:
            # A different name is another sign-up, never one to drop silently.
            if existing.name != business.name:
                raise BusinessIdTaken(tenant_id)
            return await self._sign_in_again(tenant_id, email, password)
        if await self._find_user.execute(email) is not None:
            raise EmailAlreadyInUse(email)

        tenant = await self._create_tenant.execute(business_name, tenant_id)
        admin = await self._create_user.execute(tenant.id, email, ADMIN_NAME, Role.ADMIN, password)
        session = await self._sessions.issue(admin)
        await self._uow.commit()
        return session

    async def _sign_in_again(self, tenant_id: uuid.UUID, email: str, password: str) -> AuthSession:
        """A replay of a sign-up that already went through: the same admin signs in again."""
        admin = await self._find_user.execute(email)
        if admin is None:
            await self._hasher.verify_dummy(password)
        if (
            admin is None
            or admin.tenant_id != tenant_id
            or admin.role is not Role.ADMIN
            or not await self._hasher.verify(admin.password_hash, password)
            or not admin.is_active
        ):
            raise BusinessIdTaken(tenant_id)
        session = await self._sessions.issue(admin)
        await self._uow.commit()
        return session
