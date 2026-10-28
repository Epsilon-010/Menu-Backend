import asyncio

from redis.asyncio import Redis

from app.modules.auth.infrastructure.rate_limiter import RedisLoginAttemptLimiter
from app.shared.infrastructure.config import get_settings

Step = tuple[str, str, str]  # ("acquire" | "succeed", account, client)


async def _run(steps: list[Step], max_per_client: int = 5, max_per_account: int = 50) -> list[int | None]:
    """Runs the steps; acquires in a row run concurrently."""
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        limiter = RedisLoginAttemptLimiter(
            redis, window_seconds=900, max_per_client=max_per_client, max_per_account=max_per_account
        )
        results: list[int | None] = []
        batch: list[tuple[str, str]] = []

        async def flush() -> None:
            results.extend(await asyncio.gather(*(limiter.acquire(account, client) for account, client in batch)))
            batch.clear()

        for action, account, client in steps:
            if action == "acquire":
                batch.append((account, client))
            else:
                await flush()
                await limiter.succeeded(account, client)
        await flush()
        return results
    finally:
        await redis.aclose()


def _attempts(count: int, account: str = "owner@example.com", client: str = "10.0.0.1") -> list[Step]:
    return [("acquire", account, client)] * count


def test_parallel_attempts_from_one_device_never_exceed_its_limit() -> None:
    results = asyncio.run(_run(_attempts(30)))

    assert results.count(None) == 5
    assert all(0 < wait <= 900 for wait in results if wait is not None)


def test_each_device_has_its_own_budget_on_the_same_account() -> None:
    results = asyncio.run(_run(_attempts(6) + _attempts(5, client="10.0.0.2")))

    assert results[:6].count(None) == 5
    assert results[6:] == [None] * 5


def test_each_account_has_its_own_budget_on_the_same_device() -> None:
    results = asyncio.run(_run(_attempts(6, "a@example.com") + _attempts(5, "b@example.com")))

    assert results[:6].count(None) == 5
    assert results[6:] == [None] * 5


def test_the_account_backstop_holds_however_many_devices_try() -> None:
    # A rotating or spoofed address gets a fresh device budget each time, never more than the account allows.
    steps = [step for client in range(25) for step in _attempts(3, client=f"10.0.1.{client}")]

    results = asyncio.run(_run(steps, max_per_account=50))

    assert results.count(None) == 50
    assert all(0 < wait <= 900 for wait in results if wait is not None)


def test_a_successful_login_clears_only_that_device_count() -> None:
    steps = _attempts(4) + _attempts(3, client="10.0.0.2") + [("succeed", "owner@example.com", "10.0.0.1")]

    results = asyncio.run(_run(steps + _attempts(6) + _attempts(3, client="10.0.0.2"), max_per_account=100))

    assert results[:7] == [None] * 7
    # The last two batches run concurrently: count what gets through per device.
    assert results[7:13].count(None) == 5
    # The other device keeps its 3 failures: only 2 more get through.
    assert results[13:].count(None) == 2


def test_attempts_refused_for_one_device_never_count_towards_the_account() -> None:
    # A device that keeps retrying after its own block must not exhaust the backstop and lock out the others.
    results = asyncio.run(_run(_attempts(60) + [("acquire", "owner@example.com", "10.0.0.2")], max_per_account=50))

    assert results[:60].count(None) == 5
    assert results[60] is None


def test_successful_logins_never_count_towards_the_account_backstop() -> None:
    # A tablet that signs in again and again (each attempt followed by a success) must never be blocked.
    steps: list[Step] = []
    for _ in range(60):
        steps += _attempts(1) + [("succeed", "owner@example.com", "10.0.0.1")]

    results = asyncio.run(_run(steps, max_per_account=50))

    assert results == [None] * 60


def test_successful_logins_never_take_back_failures_from_other_devices() -> None:
    # Each round: three failures from a new device run concurrently with the owner's attempt, then it signs in.
    steps: list[Step] = []
    for device in range(16):
        steps += _attempts(3, client=f"10.0.2.{device}") + _attempts(1) + [("succeed", "owner@example.com", "10.0.0.1")]
    # 48 failures so far: of the next four concurrent attempts (the owner's included) only 2 fit under the backstop.
    steps += _attempts(3, client="10.0.3.1") + _attempts(1)

    results = asyncio.run(_run(steps, max_per_account=50))

    assert results[:64] == [None] * 64
    assert results[64:].count(None) == 2
