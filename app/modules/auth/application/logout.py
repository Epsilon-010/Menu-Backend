from app.modules.auth.domain.refresh_token import RefreshTokenCodec, RefreshTokenRepository
from app.shared.domain.ports import Clock, UnitOfWork


class Logout:
    """Revokes the family of the presented refresh token; unknown or missing tokens are ignored."""

    def __init__(
        self, refresh_tokens: RefreshTokenRepository, codec: RefreshTokenCodec, clock: Clock, uow: UnitOfWork
    ) -> None:
        self._refresh_tokens = refresh_tokens
        self._codec = codec
        self._clock = clock
        self._uow = uow

    async def execute(self, plain_token: str | None) -> None:
        if not plain_token:
            return
        token = await self._refresh_tokens.get_by_hash(self._codec.hash(plain_token))
        if token is None:
            return
        await self._refresh_tokens.revoke_family(token.family_id, self._clock.now())
        await self._uow.commit()
