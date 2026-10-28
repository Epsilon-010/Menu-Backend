from redis.asyncio import Redis


class RedisLoginAttemptLimiter:
    """Fixed-window counters of login attempts per client (IP) + account, plus a per-account backstop.

    A device that keeps failing locks only itself out of that account (`max_per_client`), so nobody
    can lock a colleague or a tablet out from another device. The higher `max_per_account` caps the
    guesses from all addresses together, so rotating or spoofing the address never means unlimited
    attempts. Each attempt is counted *before* the password is checked, with atomic INCRs, so
    concurrent requests cannot slip through between a check and an increment. A successful login
    clears that client's count only: failures from other addresses still count towards the backstop.
    Each window starts at its first attempt; over a limit, logins are refused until the key expires.
    """

    def __init__(self, redis: Redis, window_seconds: int, max_per_client: int, max_per_account: int) -> None:
        self._redis = redis
        self._window_seconds = window_seconds
        self._max_per_client = max_per_client
        self._max_per_account = max_per_account

    @staticmethod
    def _client_key(account: str, client: str) -> str:
        return f"login:attempts:client:{client}:{account}"

    @staticmethod
    def _account_key(account: str) -> str:
        return f"login:attempts:account:{account}"

    async def acquire(self, account: str, client: str) -> int | None:
        client_key, account_key = self._client_key(account, client), self._account_key(account)
        async with self._redis.pipeline(transaction=True) as pipe:
            for key in (client_key, account_key):
                pipe.incr(key)
                pipe.expire(key, self._window_seconds, nx=True)
                pipe.ttl(key)
            client_count, _, client_ttl, account_count, _, account_ttl = await pipe.execute()

        waits = [
            ttl if ttl > 0 else self._window_seconds
            for count, limit, ttl in (
                (client_count, self._max_per_client, client_ttl),
                (account_count, self._max_per_account, account_ttl),
            )
            if int(count) > limit
        ]
        return max(waits) if waits else None

    async def succeeded(self, account: str, client: str) -> None:
        await self._redis.delete(self._client_key(account, client))
