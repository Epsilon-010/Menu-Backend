from redis.asyncio import Redis


class RedisLoginAttemptLimiter:
    """Fixed-window counter of login attempts per account (user), whatever IP they come from.

    Each attempt is counted *before* the password is checked, with an atomic INCR, so
    concurrent requests cannot all slip through between a check and an increment. A successful
    login clears the account's count. The window starts at the first attempt; once the counter
    goes over the limit, logins for that account are refused until the key expires.
    """

    def __init__(self, redis: Redis, window_seconds: int, max_per_account: int) -> None:
        self._redis = redis
        self._window_seconds = window_seconds
        self._max_per_account = max_per_account

    @staticmethod
    def _key(account: str) -> str:
        return f"login:attempts:account:{account}"

    async def acquire(self, account: str) -> int | None:
        key = self._key(account)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self._window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()

        if int(count) <= self._max_per_account:
            return None
        return ttl if ttl > 0 else self._window_seconds

    async def succeeded(self, account: str) -> None:
        await self._redis.delete(self._key(account))
