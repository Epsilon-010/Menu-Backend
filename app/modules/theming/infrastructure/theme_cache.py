import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.theming.domain.theme import SCHEMA_VERSION

logger = logging.getLogger(__name__)

_TTL_SECONDS = 600


class RedisThemeCache:
    """The serialized published theme of each tenant, under a generation that every publish moves on.

    Same scheme as the menu cache: a reader takes the generation before reading Postgres and stores what it
    read under that generation, so a theme read just before a publish is never served after it. Redis
    failures fail open (logged): the theme comes from Postgres.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _generation_key(tenant_id: uuid.UUID) -> str:
        return f"theme:{tenant_id}:generation"

    @staticmethod
    def _theme_key(tenant_id: uuid.UUID, generation: str) -> str:
        return f"theme:{tenant_id}:v{SCHEMA_VERSION}:{generation}"

    async def get(self, tenant_id: uuid.UUID) -> tuple[str | None, str | None]:
        """(generation, cached theme); the generation is None when Redis cannot be read."""
        try:
            generation = await self._redis.get(self._generation_key(tenant_id)) or "0"
            return generation, await self._redis.get(self._theme_key(tenant_id, generation))
        except RedisError:
            logger.warning("Could not read the cached theme of %s", tenant_id, exc_info=True)
            return None, None

    async def put(self, tenant_id: uuid.UUID, generation: str, theme: str) -> None:
        try:
            await self._redis.set(self._theme_key(tenant_id, generation), theme, ex=_TTL_SECONDS)
        except RedisError:
            logger.warning("Could not cache the theme of %s", tenant_id, exc_info=True)

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        try:
            await self._redis.incr(self._generation_key(tenant_id))
        except RedisError:
            # The cached copy expires on its own within the TTL.
            logger.warning("Could not invalidate the cached theme of %s", tenant_id, exc_info=True)
