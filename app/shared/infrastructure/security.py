from datetime import UTC, datetime
from functools import cache

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class Argon2PasswordHasher:
    """Argon2id with the library's recommended parameters."""

    def __init__(self) -> None:
        self._argon2 = _Argon2()

    def hash(self, password: str) -> str:
        return self._argon2.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._argon2.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def verify_dummy(self, password: str) -> None:
        self.verify(_dummy_hash(), password)


@cache
def _dummy_hash() -> str:
    return _Argon2().hash("dummy-password-for-unknown-accounts")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
