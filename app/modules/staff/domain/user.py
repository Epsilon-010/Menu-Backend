import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.modules.staff.domain.errors import InvalidUserData
from app.shared.domain.principal import STAFF_ROLES, Role

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 254
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    """Emails are unique across the platform and compared case-insensitively."""
    return email.strip().lower()


def validate_password(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise InvalidUserData(f"Password must have {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters")


@dataclass(frozen=True)
class User:
    """Staff account of a tenant (admin, waiter or kitchen)."""

    tenant_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    password_hash: str
    is_active: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(cls, tenant_id: uuid.UUID, email: str, full_name: str, role: Role, password_hash: str) -> "User":
        email = normalize_email(email)
        full_name = full_name.strip()
        if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(email):
            raise InvalidUserData("Invalid email")
        if not full_name or len(full_name) > MAX_NAME_LENGTH:
            raise InvalidUserData(f"Full name must have 1 to {MAX_NAME_LENGTH} characters")
        if role not in STAFF_ROLES:
            raise InvalidUserData(f"Role {role} is not a staff role")
        return cls(tenant_id=tenant_id, email=email, full_name=full_name, role=role, password_hash=password_hash)


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...
