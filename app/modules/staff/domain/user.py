import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.modules.staff.domain.errors import InvalidUserData
from app.shared.domain.principal import STAFF_ROLES, Role

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 254
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 40
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_PATTERN = re.compile(rf"^[a-z0-9._-]{{{MIN_USERNAME_LENGTH},{MAX_USERNAME_LENGTH}}}$")

# Accounts the admin manages from the staff panel (admins are not managed there).
STAFF_MEMBER_ROLES = frozenset({Role.WAITER, Role.KITCHEN})


def normalize_email(email: str) -> str:
    """Emails are unique across the platform and compared case-insensitively."""
    return email.strip().lower()


def normalize_username(username: str) -> str:
    """Usernames are unique across the platform: login receives no tenant, only the account."""
    return username.strip().lower()


def is_email_login(login: str) -> bool:
    """Admins sign in with their email, staff members with a username (which never has an @)."""
    return "@" in login


def validate_password(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise InvalidUserData(f"Password must have {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters")


def _validate_full_name(full_name: str) -> str:
    full_name = full_name.strip()
    if not full_name or len(full_name) > MAX_NAME_LENGTH:
        raise InvalidUserData(f"Full name must have 1 to {MAX_NAME_LENGTH} characters")
    return full_name


def _validate_staff_member_role(role: Role) -> Role:
    if role not in STAFF_MEMBER_ROLES:
        raise InvalidUserData("Role must be waiter or kitchen")
    return role


@dataclass(frozen=True)
class User:
    """Staff account of a tenant: an admin (signs in with email) or a waiter/cook (with username)."""

    tenant_id: uuid.UUID
    full_name: str
    role: Role
    password_hash: str
    email: str | None = None
    username: str | None = None
    is_active: bool = True
    # Goes up whenever the member must be signed out (new password, role change, deactivation): every
    # session token carries the version it was issued for, so an older one is rejected.
    session_version: int = 1
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(cls, tenant_id: uuid.UUID, email: str, full_name: str, role: Role, password_hash: str) -> "User":
        email = normalize_email(email)
        if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(email):
            raise InvalidUserData("Invalid email")
        full_name = _validate_full_name(full_name)
        if role not in STAFF_ROLES:
            raise InvalidUserData(f"Role {role} is not a staff role")
        return cls(tenant_id=tenant_id, email=email, full_name=full_name, role=role, password_hash=password_hash)

    @classmethod
    def create_staff(
        cls,
        tenant_id: uuid.UUID,
        username: str,
        full_name: str,
        role: Role,
        password_hash: str,
        user_id: uuid.UUID | None = None,
    ) -> "User":
        """`user_id` comes from the client to make the create idempotent; None generates one."""
        username = normalize_username(username)
        if not _USERNAME_PATTERN.match(username):
            raise InvalidUserData(
                f"Username must have {MIN_USERNAME_LENGTH} to {MAX_USERNAME_LENGTH} characters: "
                "letters, digits, dots, hyphens or underscores"
            )
        return cls(
            tenant_id=tenant_id,
            username=username,
            full_name=_validate_full_name(full_name),
            role=_validate_staff_member_role(role),
            password_hash=password_hash,
            id=user_id or uuid.uuid4(),
        )

    @property
    def is_staff_member(self) -> bool:
        return self.role in STAFF_MEMBER_ROLES

    def with_changes(
        self, full_name: str | None = None, role: Role | None = None, is_active: bool | None = None
    ) -> "User":
        return replace(
            self,
            full_name=self.full_name if full_name is None else _validate_full_name(full_name),
            role=self.role if role is None else _validate_staff_member_role(role),
            is_active=self.is_active if is_active is None else is_active,
        )

    def with_sessions_ended(self) -> "User":
        return replace(self, session_version=self.session_version + 1)


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None: ...

    async def get_for_update(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        """Same as `get`, locking the row until the transaction ends: for every read-then-write."""
        ...

    async def exists_anywhere(self, user_id: uuid.UUID) -> bool:
        """Whether the id is taken in any tenant (to answer a clash without revealing that row)."""
        ...

    async def lock_creates(self, tenant_id: uuid.UUID) -> None:
        """Serializes the tenant's staff creates until the transaction ends, so a concurrent replay
        of a create waits for the first one and then finds it."""
        ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_username(self, username: str) -> User | None: ...

    async def list_staff(self, tenant_id: uuid.UUID) -> list[User]:
        """Waiters and cooks of the tenant, ordered by name."""
        ...

    async def update(self, user: User) -> None: ...


class SessionRevoker(Protocol):
    """Port: ends every session of a user right away (implemented by the auth module).

    It does not commit: the calling use case owns the transaction.
    """

    async def revoke_all(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None: ...

    async def end_access(self, user_id: uuid.UUID, session_version: int) -> None:
        """Rejects live access tokens older than `session_version`. Call it after the commit that
        stored that version: before it, a failed commit would leave new logins rejected."""
        ...
