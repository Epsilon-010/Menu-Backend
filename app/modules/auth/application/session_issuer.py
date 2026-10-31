import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.auth.domain.refresh_token import (
    AccessTokenIssuer,
    RefreshToken,
    RefreshTokenCodec,
    RefreshTokenRepository,
    refresh_token_ttl,
)
from app.modules.orders.domain.model import Guest
from app.modules.staff.domain.user import User
from app.modules.tables.domain.table import Table
from app.shared.domain.ports import Clock
from app.shared.domain.principal import Role


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    role: Role
    must_change_password: bool = False


class SessionIssuer:
    """Issues an access token plus a new refresh token in the given (or a new) family.

    It stores the refresh token but does not commit: the calling use case owns the transaction.
    """

    def __init__(
        self,
        refresh_tokens: RefreshTokenRepository,
        codec: RefreshTokenCodec,
        access_tokens: AccessTokenIssuer,
        clock: Clock,
    ) -> None:
        self._refresh_tokens = refresh_tokens
        self._codec = codec
        self._access_tokens = access_tokens
        self._clock = clock

    async def issue(self, user: User, family_id: uuid.UUID | None = None) -> AuthSession:
        return await self._issue(
            user.id,
            user.tenant_id,
            user.role,
            family_id,
            user.session_version,
            user_id=user.id,
            must_change_password=user.must_change_password,
        )

    async def issue_for_table(self, table: Table, family_id: uuid.UUID | None = None) -> AuthSession:
        """The table is both the token subject and its `table_id` claim."""
        return await self._issue(
            table.id, table.tenant_id, Role.TABLE, family_id, table.session_version, table_id=table.id
        )

    async def issue_for_guest(self, guest: Guest, family_id: uuid.UUID | None = None) -> AuthSession:
        """The guest is the subject; the session acts as their table, only on the bill they joined, and
        never outlives their visit limit however often it is refreshed."""
        return await self._issue(
            guest.id,
            guest.tenant_id,
            Role.GUEST,
            family_id,
            1,
            guest_id=guest.id,
            claim_table_id=guest.table_id,
            bill_id=guest.bill_id,
            expires_by=guest.ends_at,
        )

    async def _issue(
        self,
        subject_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: Role,
        family_id: uuid.UUID | None,
        session_version: int,
        user_id: uuid.UUID | None = None,
        table_id: uuid.UUID | None = None,
        guest_id: uuid.UUID | None = None,
        claim_table_id: uuid.UUID | None = None,
        bill_id: uuid.UUID | None = None,
        expires_by: datetime | None = None,
        must_change_password: bool = False,
    ) -> AuthSession:
        now = self._clock.now()
        plain = self._codec.generate()
        expires_at = now + refresh_token_ttl(role)
        refresh = RefreshToken(
            tenant_id=tenant_id,
            user_id=user_id,
            table_id=table_id,
            guest_id=guest_id,
            family_id=family_id or uuid.uuid4(),
            token_hash=self._codec.hash(plain),
            created_at=now,
            expires_at=min(expires_at, expires_by) if expires_by is not None else expires_at,
            session_version=session_version,
        )
        await self._refresh_tokens.add(refresh)
        access = self._access_tokens.issue(
            subject_id,
            tenant_id,
            role,
            now,
            session_version=session_version,
            table_id=table_id or claim_table_id,
            bill_id=bill_id,
            must_change_password=must_change_password,
        )
        return AuthSession(
            access_token=access.token,
            access_expires_at=access.expires_at,
            refresh_token=plain,
            refresh_expires_at=refresh.expires_at,
            role=role,
            must_change_password=must_change_password,
        )
