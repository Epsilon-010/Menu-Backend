from datetime import UTC, datetime
from functools import cache

from anyio import to_thread
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class Argon2PasswordHasher:
    """Argon2id with the library's recommended parameters.

    Hashing runs in a worker thread so a burst of logins does not block the event loop.
    """

    def __init__(self) -> None:
        self._argon2 = _Argon2()

    async def hash(self, password: str) -> str:
        return await to_thread.run_sync(self._argon2.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        return await to_thread.run_sync(self._verify_sync, password_hash, password)

    async def verify_dummy(self, password: str) -> None:
        await to_thread.run_sync(self._verify_sync, _dummy_hash(), password)

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
