import uuid
from datetime import UTC, datetime
from typing import Any

from jose import JWTError, jwt

from app.modules.auth.domain.refresh_token import ACCESS_TOKEN_TTL, IssuedAccessToken
from app.shared.domain.principal import InvalidAccessToken, Principal, Role

_ALGORITHM = "HS256"
_REQUIRED_CLAIMS = ("sub", "tenant_id", "role", "exp", "iat", "jti", "sv")


class JoseAccessTokens:
    """Signs and verifies HS256 access tokens. Only HS256 is accepted on decode."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def issue(
        self,
        subject_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: Role,
        now: datetime,
        *,
        session_version: int,
        table_id: uuid.UUID | None = None,
    ) -> IssuedAccessToken:
        expires_at = now + ACCESS_TOKEN_TTL
        claims: dict[str, Any] = {
            "sub": str(subject_id),
            "tenant_id": str(tenant_id),
            "role": role.value,
            "jti": str(uuid.uuid4()),
            # NumericDate with sub-second precision, compared against session revocations.
            "iat": now.timestamp(),
            "exp": expires_at.timestamp(),
            # The subject's session version: a credential change makes the token stale.
            "sv": session_version,
        }
        if table_id is not None:
            claims["table_id"] = str(table_id)
        return IssuedAccessToken(token=jwt.encode(claims, self._secret, algorithm=_ALGORITHM), expires_at=expires_at)

    def decode(self, token: str) -> Principal:
        try:
            claims = jwt.decode(token, self._secret, algorithms=[_ALGORITHM])
            if any(name not in claims for name in _REQUIRED_CLAIMS):
                raise InvalidAccessToken()
            role = Role(claims["role"])
            table_id = claims.get("table_id")
            if role is Role.TABLE and not table_id:
                raise InvalidAccessToken()
            session_version = claims["sv"]
            if type(session_version) is not int or session_version < 1:
                raise InvalidAccessToken()
            return Principal(
                subject_id=uuid.UUID(claims["sub"]),
                tenant_id=uuid.UUID(claims["tenant_id"]),
                role=role,
                table_id=uuid.UUID(table_id) if role is Role.TABLE else None,
                issued_at=datetime.fromtimestamp(float(claims["iat"]), UTC),
                session_version=session_version,
            )
        except (JWTError, ValueError, TypeError, OverflowError) as error:
            raise InvalidAccessToken() from error
