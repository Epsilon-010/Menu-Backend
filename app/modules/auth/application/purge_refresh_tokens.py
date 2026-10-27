"""Periodic purge of refresh tokens nobody can use any more (runs in the Celery worker)."""

from datetime import timedelta

from app.modules.auth.domain.refresh_token import RefreshTokenRepository
from app.shared.domain.ports import Clock, UnitOfWork

BATCH_SIZE = 1000


class PurgeExpiredRefreshTokens:
    """Deletes tokens expired for longer than `grace`.

    Only expiry matters: a rotated or revoked token that is still within its lifetime is kept,
    because presenting it again is how the theft of a session is detected (the whole family is
    revoked). Once expired, a token is refused anyway, so its row only takes space.
    """

    def __init__(self, tokens: RefreshTokenRepository, clock: Clock, uow: UnitOfWork, grace: timedelta) -> None:
        self._tokens = tokens
        self._clock = clock
        self._uow = uow
        self._grace = grace

    async def execute(self) -> int:
        purged = await self._tokens.delete_expired(self._clock.now() - self._grace, BATCH_SIZE)
        await self._uow.commit()
        return purged
