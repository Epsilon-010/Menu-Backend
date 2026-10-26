from redis.asyncio import Redis


def create_redis(redis_url: str) -> Redis:
    return Redis.from_url(redis_url, decode_responses=True)


class RedisProbe:
    name = "redis"

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def is_healthy(self) -> bool:
        return bool(await self._client.ping())
