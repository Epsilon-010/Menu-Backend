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


STAFF_ROLES = frozenset({Role.ADMIN, Role.WAITER, Role.KITCHEN})


class InvalidAccessToken(Exception):
    """The access token is missing, malformed, expired or not signed by us."""


class AccessTokenDecoder(Protocol):
    """Port: turns a bearer access token into the authenticated principal."""

    def decode(self, token: str) -> "Principal":
        """Raises InvalidAccessToken when the token cannot be trusted."""
        ...


class AccessRevocations(Protocol):
    """Port: access tokens are stateless, so ending a subject's sessions right away also records
    when it happened; tokens issued at or before that moment are rejected until they expire."""

    async def revoke(self, subject_id: uuid.UUID, at: datetime) -> None: ...

    async def revoked_since(self, subject_id: uuid.UUID) -> datetime | None: ...


@dataclass(frozen=True)
class Principal:
    """Authenticated caller, always taken from the access token (never from the body or URL).

    `subject_id` is the user id for staff roles and the table id for the `table` role.
    """

    subject_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role
    table_id: uuid.UUID | None = None
    issued_at: datetime | None = None
