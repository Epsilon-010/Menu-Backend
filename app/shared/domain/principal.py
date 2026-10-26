import uuid
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    WAITER = "waiter"
    KITCHEN = "kitchen"
    TABLE = "table"


STAFF_ROLES = frozenset({Role.ADMIN, Role.WAITER, Role.KITCHEN})


@dataclass(frozen=True)
class Principal:
    """Authenticated caller, always taken from the access token (never from the body or URL).

    `subject_id` is the user id for staff roles and the table id for the `table` role.
    """

    subject_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role
    table_id: uuid.UUID | None = None
