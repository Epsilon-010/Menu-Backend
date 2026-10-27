from typing import NoReturn

from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import InvalidRefreshToken
from app.modules.auth.domain.refresh_token import RefreshToken, RefreshTokenCodec, RefreshTokenRepository
from app.modules.staff.application.find_user import GetUser
from app.modules.tables.application.find_table import GetTable
from app.shared.domain.ports import Clock, UnitOfWork


class RefreshSession:
    """Rotates a refresh token. Presenting an already rotated token revokes its whole family."""

    def __init__(
        self,
        refresh_tokens: RefreshTokenRepository,
        codec: RefreshTokenCodec,
        get_user: GetUser,
        get_table: GetTable,
        sessions: SessionIssuer,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._refresh_tokens = refresh_tokens
        self._codec = codec
        self._get_user = get_user
        self._get_table = get_table
        self._sessions = sessions
        self._clock = clock
        self._uow = uow

    async def execute(self, plain_token: str) -> AuthSession:
        if not plain_token:
            raise InvalidRefreshToken()
        token = await self._refresh_tokens.get_by_hash(self._codec.hash(plain_token))
        if token is None or token.revoked_at is not None:
            raise InvalidRefreshToken()

        now = self._clock.now()
        if token.rotated_at is not None:
            await self._revoke_family_and_reject(token)
        if token.is_expired(now):
            raise InvalidRefreshToken()

        if token.table_id is not None:
            table = await self._get_table.execute(token.tenant_id, token.table_id)
            if table is None or not table.is_active:
                await self._revoke_family_and_reject(token)
            await self._rotate(token)
            session = await self._sessions.issue_for_table(table, family_id=token.family_id)
        elif token.user_id is not None:
            user = await self._get_user.execute(token.tenant_id, token.user_id)
            if user is None or not user.is_active:
                await self._revoke_family_and_reject(token)
            await self._rotate(token)
            session = await self._sessions.issue(user, family_id=token.family_id)
        else:
            raise InvalidRefreshToken()
        await self._uow.commit()
        return session

    async def _rotate(self, token: RefreshToken) -> None:
        if not await self._refresh_tokens.mark_rotated(token.id, self._clock.now()):
            await self._revoke_family_and_reject(token)

    async def _revoke_family_and_reject(self, token: RefreshToken) -> NoReturn:
        await self._refresh_tokens.revoke_family(token.family_id, self._clock.now())
        await self._uow.commit()
        raise InvalidRefreshToken()
