from redis.asyncio import Redis


class RedisLoginAttemptLimiter:
    """Fixed-window counters of failed logins, one per client IP and one per account.

    The window starts at the first failure; once a counter reaches its limit, logins for that
    IP or account are refused until the key expires.
    """

    def __init__(self, redis: Redis, window_seconds: int, max_per_account: int, max_per_ip: int) -> None:
        self._redis = redis
        self._window_seconds = window_seconds
        self._max_per_account = max_per_account
        self._max_per_ip = max_per_ip

    @staticmethod
    def _ip_key(client_ip: str) -> str:
        return f"login:failures:ip:{client_ip}"

    @staticmethod
    def _account_key(account: str) -> str:
        return f"login:failures:account:{account}"

    async def retry_after(self, client_ip: str, account: str) -> int | None:
        checks = [(self._ip_key(client_ip), self._max_per_ip), (self._account_key(account), self._max_per_account)]
        async with self._redis.pipeline(transaction=False) as pipe:
            for key, _ in checks:
                pipe.get(key)
                pipe.ttl(key)
            results = await pipe.execute()

        waits = [
            ttl if ttl > 0 else self._window_seconds
            for (_, limit), count, ttl in zip(checks, results[0::2], results[1::2], strict=True)
            if count is not None and int(count) >= limit
        ]
        return max(waits) if waits else None

    async def record_failure(self, client_ip: str, account: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            for key in (self._ip_key(client_ip), self._account_key(account)):
                pipe.incr(key)
                pipe.expire(key, self._window_seconds, nx=True)
            await pipe.execute()

    async def reset(self, account: str) -> None:
        await self._redis.delete(self._account_key(account))
