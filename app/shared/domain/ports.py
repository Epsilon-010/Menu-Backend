from datetime import datetime
from typing import Protocol


class UnitOfWork(Protocol):
    """Port: makes the changes of the current use case durable, all or nothing."""

    async def commit(self) -> None: ...


class Clock(Protocol):
    """Port: current time (timezone-aware UTC)."""

    def now(self) -> datetime: ...


class PasswordHasher(Protocol):
    """Port: one-way password hashing (Argon2 in production)."""

    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def verify_dummy(self, password: str) -> None:
        """Spends the same time as `verify`, so unknown accounts cannot be detected by timing."""
        ...
