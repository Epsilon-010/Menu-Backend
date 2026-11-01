from redis.asyncio import Redis


def create_redis(redis_url: str, max_connections: int | None = None) -> Redis:
    """`max_connections` sizes the client's own pool (redis-py's default is 100)."""
    if max_connections is None:
        return Redis.from_url(redis_url, decode_responses=True)
    return Redis.from_url(redis_url, decode_responses=True, max_connections=max_connections)


class RedisProbe:
    name = "redis"

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def is_healthy(self) -> bool:
        return bool(await self._client.ping())
