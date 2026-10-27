import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Role(StrEnum):
    ADMIN = "admin"
    WAITER = "waiter"
    KITCHEN = "kitchen"
    TABLE = "table"


STAFF_ROLES = frozenset({Role.ADMIN, Role.WAITER, Role.KITCHEN})


class InvalidAccessToken(Exception):
    """The access token is missing, malformed, expired or not signed by us."""


class AccessTokenDecoder(Protocol):
    """Port: turns a bearer access token into the authenticated principal."""

    def decode(self, token: str) -> "Principal":
        """Raises InvalidAccessToken when the token cannot be trusted."""
        ...


@dataclass(frozen=True)
class Principal:
    """Authenticated caller, always taken from the access token (never from the body or URL).

    `subject_id` is the user id for staff roles and the table id for the `table` role.
    """

    subject_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role
    table_id: uuid.UUID | None = None
