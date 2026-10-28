import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_TTL_SECONDS = 600


class RedisMenuCache:
    """The serialized menu of each tenant, under a generation that every catalog change moves on.

    A reader takes the generation before reading Postgres and stores what it read under that
    generation, so a menu read just before a change can never be served after it: the change already
    moved readers to the next generation. Redis failures fail open (logged): the menu comes from Postgres.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _generation_key(tenant_id: uuid.UUID) -> str:
        return f"menu:{tenant_id}:generation"

    @staticmethod
    def _menu_key(tenant_id: uuid.UUID, generation: str) -> str:
        return f"menu:{tenant_id}:{generation}"

    async def get(self, tenant_id: uuid.UUID) -> tuple[str | None, str | None]:
        """(generation, cached menu); the generation is None when Redis cannot be read."""
        try:
            generation = await self._redis.get(self._generation_key(tenant_id)) or "0"
            return generation, await self._redis.get(self._menu_key(tenant_id, generation))
        except RedisError:
            logger.warning("Could not read the cached menu of %s", tenant_id, exc_info=True)
            return None, None

    async def put(self, tenant_id: uuid.UUID, generation: str, menu: str) -> None:
        try:
            await self._redis.set(self._menu_key(tenant_id, generation), menu, ex=_TTL_SECONDS)
        except RedisError:
            logger.warning("Could not cache the menu of %s", tenant_id, exc_info=True)

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        try:
            await self._redis.incr(self._generation_key(tenant_id))
        except RedisError:
            # The cached copy expires on its own within the TTL.
            logger.warning("Could not invalidate the cached menu of %s", tenant_id, exc_info=True)
