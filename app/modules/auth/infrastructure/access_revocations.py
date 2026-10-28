import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.auth.domain.refresh_token import ACCESS_TOKEN_TTL

logger = logging.getLogger(__name__)

# Sets the key only when it is missing or lower, so two credential changes finishing out of order
# never lower the required version; every write renews the expiry.
_RAISE_VERSION = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local wanted = tonumber(ARGV[1])
if wanted > current then current = wanted end
redis.call('SET', KEYS[1], current, 'EX', ARGV[2])
return current
"""


class RedisAccessRevocations:
    """Remembers the session version a subject's access tokens need, for as long as one can live.

    After ACCESS_TOKEN_TTL (plus a margin for a login that read the old version just before the
    change) every older token has expired on its own, so the key expires too. Redis failures fail
    open (logged): the refresh tokens are already revoked or stale in Postgres, so the session still
    ends within one access-token lifetime, and an outage does not sign every device out.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._ttl_seconds = int(ACCESS_TOKEN_TTL.total_seconds()) + 60

    @staticmethod
    def _key(subject_id: uuid.UUID) -> str:
        return f"auth:session-version:{subject_id}"

    async def require_version(self, subject_id: uuid.UUID, session_version: int) -> None:
        try:
            await self._redis.eval(_RAISE_VERSION, 1, self._key(subject_id), session_version, self._ttl_seconds)
        except RedisError:
            logger.warning("Could not record the session version of %s", subject_id, exc_info=True)

    async def required_version(self, subject_id: uuid.UUID) -> int | None:
        try:
            value = await self._redis.get(self._key(subject_id))
        except RedisError:
            logger.warning("Could not check the session version of %s", subject_id, exc_info=True)
            return None
        return int(value) if value is not None else None
