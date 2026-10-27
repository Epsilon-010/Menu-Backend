import logging
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.auth.domain.refresh_token import ACCESS_TOKEN_TTL

logger = logging.getLogger(__name__)


class RedisAccessRevocations:
    """Remembers when a subject's sessions were revoked, for as long as an access token can live.

    After ACCESS_TOKEN_TTL every token issued before the revocation has expired on its own, so
    the key expires too. Redis failures fail open (logged): the refresh tokens are already
    revoked in Postgres, so the session still ends within one access-token lifetime, and an
    outage does not sign every device out.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._ttl_seconds = int(ACCESS_TOKEN_TTL.total_seconds()) + 60

    @staticmethod
    def _key(subject_id: uuid.UUID) -> str:
        return f"auth:revoked:{subject_id}"

    async def revoke(self, subject_id: uuid.UUID, at: datetime) -> None:
        try:
            await self._redis.set(self._key(subject_id), repr(at.timestamp()), ex=self._ttl_seconds)
        except RedisError:
            logger.warning("Could not record the access revocation of %s", subject_id, exc_info=True)

    async def revoked_since(self, subject_id: uuid.UUID) -> datetime | None:
        try:
            value = await self._redis.get(self._key(subject_id))
        except RedisError:
            logger.warning("Could not check the access revocation of %s", subject_id, exc_info=True)
            return None
        return datetime.fromtimestamp(float(value), UTC) if value is not None else None
