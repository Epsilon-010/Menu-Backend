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
from app.modules.staff.domain.user import User
from app.shared.domain.ports import Clock
from app.shared.domain.principal import Role


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    role: Role


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
        now = self._clock.now()
        plain = self._codec.generate()
        refresh = RefreshToken(
            tenant_id=user.tenant_id,
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=self._codec.hash(plain),
            created_at=now,
            expires_at=now + refresh_token_ttl(user.role),
        )
        await self._refresh_tokens.add(refresh)
        access = self._access_tokens.issue(user.id, user.tenant_id, user.role, now)
        return AuthSession(
            access_token=access.token,
            access_expires_at=access.expires_at,
            refresh_token=plain,
            refresh_expires_at=refresh.expires_at,
            role=user.role,
        )
