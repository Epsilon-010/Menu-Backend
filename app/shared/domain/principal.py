import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Role(StrEnum):
    ADMIN = "admin"
    WAITER = "waiter"
    KITCHEN = "kitchen"
    TABLE = "table"
    # Someone who joined an open table by its QR; acts as the table only during that visit.
    GUEST = "guest"


STAFF_ROLES = frozenset({Role.ADMIN, Role.WAITER, Role.KITCHEN})


class InvalidAccessToken(Exception):
    """The access token is missing, malformed, expired or not signed by us."""


class AccessTokenDecoder(Protocol):
    """Port: turns a bearer access token into the authenticated principal."""

    def decode(self, token: str) -> "Principal":
        """Raises InvalidAccessToken when the token cannot be trusted."""
        ...


class AccessRevocations(Protocol):
    """Port: access tokens are stateless, so ending a subject's sessions right away also records the
    session version a token needs; older tokens are rejected until they expire on their own."""

    async def require_version(self, subject_id: uuid.UUID, session_version: int) -> None:
        """Never lowers an already required version."""
        ...

    async def required_version(self, subject_id: uuid.UUID) -> int | None: ...


@dataclass(frozen=True)
class Principal:
    """Authenticated caller, always taken from the access token (never from the body or URL).

    `subject_id` is the user id for staff roles, the table id for the `table` role and the guest id for
    `guest`, whose `bill_id` is the visit they joined.
    """

    subject_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role
    table_id: uuid.UUID | None = None
    issued_at: datetime | None = None
    session_version: int = 1
    bill_id: uuid.UUID | None = None
    # An admin still on a temporary password: may only change it (and sign out).
    must_change_password: bool = False
