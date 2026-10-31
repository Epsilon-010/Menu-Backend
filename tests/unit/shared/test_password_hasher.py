import asyncio
import threading
import time

import pytest

from app.shared.infrastructure import security
from app.shared.infrastructure.security import Argon2PasswordHasher


def test_concurrent_password_checks_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each Argon2 check takes ~64 MiB: a login flood must queue, not run 40 of them at once.
    lock = threading.Lock()
    running = 0
    most = 0

    def slow_check(self: Argon2PasswordHasher, password_hash: str, password: str) -> bool:
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
        time.sleep(0.02)
        with lock:
            running -= 1
        return False

    monkeypatch.setattr(security, "MAX_CONCURRENT_HASHES", 3)
    monkeypatch.setattr(Argon2PasswordHasher, "_verify_sync", slow_check)

    async def flood() -> None:
        hashers = [Argon2PasswordHasher() for _ in range(4)]  # one per request, as the routers do
        await asyncio.gather(*(hashers[n % 4].verify("hash", "guess") for n in range(24)))
        await asyncio.gather(*(hashers[n % 4].verify_dummy("guess") for n in range(12)))

    asyncio.run(flood())

    assert most == 3
