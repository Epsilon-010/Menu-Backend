from redis.asyncio import Redis


class RedisLoginAttemptLimiter:
    """Fixed-window counters of login attempts, one per client IP and one per account.

    Each attempt is counted *before* the password is checked, with an atomic INCR, so
    concurrent requests cannot all slip through between a check and an increment. A successful
    login gives its attempt back. The window starts at the first attempt; once a counter goes
    over its limit, logins for that IP or account are refused until the key expires.
    """

    def __init__(self, redis: Redis, window_seconds: int, max_per_account: int, max_per_ip: int) -> None:
        self._redis = redis
        self._window_seconds = window_seconds
        self._max_per_account = max_per_account
        self._max_per_ip = max_per_ip

    @staticmethod
    def _ip_key(client_ip: str) -> str:
        return f"login:attempts:ip:{client_ip}"

    @staticmethod
    def _account_key(account: str) -> str:
        return f"login:attempts:account:{account}"

    async def acquire(self, client_ip: str, account: str) -> int | None:
        checks = [(self._ip_key(client_ip), self._max_per_ip), (self._account_key(account), self._max_per_account)]
        async with self._redis.pipeline(transaction=True) as pipe:
            for key, _ in checks:
                pipe.incr(key)
                pipe.expire(key, self._window_seconds, nx=True)
                pipe.ttl(key)
            results = await pipe.execute()

        counts, ttls = results[0::3], results[2::3]
        waits = [
            ttl if ttl > 0 else self._window_seconds
            for (_, limit), count, ttl in zip(checks, counts, ttls, strict=True)
            if int(count) > limit
        ]
        return max(waits) if waits else None

    async def succeeded(self, client_ip: str, account: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(self._account_key(account))
            pipe.decr(self._ip_key(client_ip))
            await pipe.execute()
