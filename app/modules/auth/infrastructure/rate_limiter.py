from redis.asyncio import Redis

# KEYS: client counter, account counter. ARGV: window, client limit, account limit.
# Returns the seconds to wait when over a limit, else 0. The account counter only moves while the
# client is within its own limit.
_ACQUIRE = """
local function count(key)
  local value = redis.call('INCR', key)
  if value == 1 then redis.call('EXPIRE', key, ARGV[1]) end
  return value
end
local function wait(key)
  local ttl = redis.call('TTL', key)
  if ttl > 0 then return ttl end
  return tonumber(ARGV[1])
end
if count(KEYS[1]) > tonumber(ARGV[2]) then return wait(KEYS[1]) end
if count(KEYS[2]) > tonumber(ARGV[3]) then return wait(KEYS[2]) end
return 0
"""


class RedisLoginAttemptLimiter:
    """Fixed-window counters of login attempts per client (IP) + account, plus a per-account backstop.

    A device that keeps failing locks only itself out of that account (`max_per_client`), so nobody
    can lock a colleague or a tablet out from another device. The higher `max_per_account` caps the
    guesses from all addresses together, so rotating or spoofing the address never means unlimited
    attempts. Attempts a client makes while it is already blocked never reach the account counter,
    so one device retrying in a loop cannot exhaust the backstop for everyone else. Each attempt is
    counted *before* the password is checked, in one atomic script, so concurrent requests cannot
    slip through between a check and an increment. A successful login clears that client's count
    only: failures from other addresses still count towards the backstop. Each window starts at its
    first attempt; over a limit, logins are refused until the key expires.
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
        wait = await self._redis.eval(
            _ACQUIRE,
            2,
            self._client_key(account, client),
            self._account_key(account),
            self._window_seconds,
            self._max_per_client,
            self._max_per_account,
        )
        return int(wait) if int(wait) > 0 else None

    async def succeeded(self, account: str, client: str) -> None:
        await self._redis.delete(self._client_key(account, client))
