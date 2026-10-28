import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from app.shared.domain.principal import Role

ACCESS_TOKEN_TTL = timedelta(minutes=15)

_REFRESH_TOKEN_TTL = {
    Role.ADMIN: timedelta(days=7),
    Role.WAITER: timedelta(hours=12),
    Role.KITCHEN: timedelta(hours=12),
    Role.TABLE: timedelta(days=30),
}


def refresh_token_ttl(role: Role) -> timedelta:
    """Admin: 7 days; waiter and kitchen: one 12-hour shift; table devices: 30 days."""
    return _REFRESH_TOKEN_TTL[role]


@dataclass(frozen=True)
class RefreshToken:
    """Stored refresh token. Only its hash is kept; the plain value lives in the client cookie.

    Every rotation creates a new token in the same family; presenting an already rotated
    token is treated as theft and revokes the whole family.
    """

    tenant_id: uuid.UUID
    # Exactly one of them: the staff member or the table device the session belongs to.
    user_id: uuid.UUID | None
    family_id: uuid.UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    table_id: uuid.UUID | None = None
    # The owner's session version when it was issued; a credential change makes it stale.
    session_version: int = 1
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        if (self.user_id is None) == (self.table_id is None):
            raise ValueError("A refresh token belongs to exactly one user or table")

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


class RefreshTokenRepository(Protocol):
    async def add(self, token: RefreshToken) -> None: ...

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Returns the token locked for the current transaction."""
        ...

    async def mark_rotated(self, token_id: uuid.UUID, at: datetime) -> bool:
        """Marks the token rotated only if it is still active; False when someone else won the race."""
        ...

    async def revoke_family(self, family_id: uuid.UUID, at: datetime) -> None: ...

    async def revoke_all_for_user(self, tenant_id: uuid.UUID, user_id: uuid.UUID, at: datetime) -> None: ...

    async def revoke_all_for_table(self, tenant_id: uuid.UUID, table_id: uuid.UUID, at: datetime) -> None: ...

    async def delete_expired(self, before: datetime, limit: int) -> int:
        """Deletes up to `limit` tokens that expired before `before` (all tenants); returns how many."""
        ...


class RefreshTokenCodec(Protocol):
    """Port: creates opaque refresh token values and the hash stored for them."""

    def generate(self) -> str: ...

    def hash(self, token: str) -> str: ...


@dataclass(frozen=True)
class IssuedAccessToken:
    token: str
    expires_at: datetime


class AccessTokenIssuer(Protocol):
    """Port: signs short-lived access tokens."""

    def issue(
        self,
        subject_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: Role,
        now: datetime,
        *,
        session_version: int,
        table_id: uuid.UUID | None = None,
    ) -> IssuedAccessToken: ...


class LoginAttemptLimiter(Protocol):
    """Port: limits login attempts per client (IP) and account, so a device that keeps failing only
    locks itself out; a higher per-account backstop still caps guessing from many addresses."""

    async def acquire(self, account: str, client: str) -> int | None:
        """Atomically counts this attempt before the password is checked.

        Returns the seconds until a new attempt is allowed when over a limit, else None.
        """
        ...

    async def succeeded(self, account: str, client: str) -> None:
        """Clears this client's count for the account after a successful login."""
        ...
