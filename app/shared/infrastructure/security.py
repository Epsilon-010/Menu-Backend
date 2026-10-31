import asyncio
import os
from datetime import UTC, datetime
from functools import cache
from weakref import WeakKeyDictionary

from anyio import CapacityLimiter, to_thread
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


# Each Argon2 hash takes ~64 MiB and a CPU core for tens of milliseconds: past this many at once, a
# burst of logins waits in line instead of exhausting the memory of the API.
MAX_CONCURRENT_HASHES = max(2, os.cpu_count() or 2)
_hashing_slots: "WeakKeyDictionary[asyncio.AbstractEventLoop, CapacityLimiter]" = WeakKeyDictionary()


def _slots() -> CapacityLimiter:
    """Shared by every hasher of the event loop (the routers build one per request)."""
    loop = asyncio.get_running_loop()
    slots = _hashing_slots.get(loop)
    if slots is None:
        slots = _hashing_slots[loop] = CapacityLimiter(MAX_CONCURRENT_HASHES)
    return slots


class Argon2PasswordHasher:
    """Argon2id with the library's recommended parameters.

    Hashing runs in a worker thread so a burst of logins does not block the event loop, and at most
    `MAX_CONCURRENT_HASHES` run at once.
    """

    def __init__(self) -> None:
        self._argon2 = _Argon2()

    async def hash(self, password: str) -> str:
        return await to_thread.run_sync(self._argon2.hash, password, limiter=_slots())

    async def verify(self, password_hash: str, password: str) -> bool:
        return await to_thread.run_sync(self._verify_sync, password_hash, password, limiter=_slots())

    async def verify_dummy(self, password: str) -> None:
        await to_thread.run_sync(self._verify_sync, _dummy_hash(), password, limiter=_slots())

    def _verify_sync(self, password_hash: str, password: str) -> bool:
        try:
            return self._argon2.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


@cache
def _dummy_hash() -> str:
    return _Argon2().hash("dummy-password-for-unknown-accounts")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
