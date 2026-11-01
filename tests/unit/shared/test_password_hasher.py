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


def test_waiting_like_a_check_takes_as_long_as_one_but_never_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    checks: list[str] = []

    def slow_check(self: Argon2PasswordHasher, password_hash: str, password: str) -> bool:
        checks.append(password)
        time.sleep(0.05)
        return False

    monkeypatch.setattr(Argon2PasswordHasher, "_verify_sync", slow_check)
    monkeypatch.setattr(security, "_check_seconds", None)

    async def run() -> float:
        hasher = Argon2PasswordHasher()
        await hasher.verify_dummy("guess")  # a real check: the wait learns how long one takes
        before = time.perf_counter()
        for _ in range(3):
            await hasher.wait_like_verify()
        return (time.perf_counter() - before) / 3

    waited = asyncio.run(run())

    assert checks == ["guess"]
    assert 0.04 <= waited <= 0.2
