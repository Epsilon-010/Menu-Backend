import asyncio

from redis.asyncio import Redis

from app.modules.auth.infrastructure.rate_limiter import RedisLoginAttemptLimiter
from app.shared.infrastructure.config import get_settings


async def _run(steps: list[tuple[str, str]], max_per_account: int = 5) -> list[int | None]:
    """Runs ("acquire" | "succeed", account) steps; acquires in a row run concurrently."""
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        limiter = RedisLoginAttemptLimiter(redis, window_seconds=900, max_per_account=max_per_account)
        results: list[int | None] = []
        batch: list[str] = []

        async def flush() -> None:
            results.extend(await asyncio.gather(*(limiter.acquire(account) for account in batch)))
            batch.clear()

        for action, account in steps:
            if action == "acquire":
                batch.append(account)
            else:
                await flush()
                await limiter.succeeded(account)
        await flush()
        return results
    finally:
        await redis.aclose()


def test_parallel_attempts_on_one_account_never_exceed_its_limit() -> None:
    # However many clients (IPs) attack the same user, only 5 attempts get through.
    results = asyncio.run(_run([("acquire", "owner@example.com")] * 30))

    assert results.count(None) == 5
    assert all(0 < wait <= 900 for wait in results if wait is not None)


def test_each_account_has_its_own_budget() -> None:
    results = asyncio.run(_run([("acquire", "a@example.com")] * 6 + [("acquire", "b@example.com")] * 5))

    assert results[:6].count(None) == 5
    assert results[6:] == [None] * 5


def test_a_successful_login_clears_the_account_count() -> None:
    steps = [("acquire", "owner@example.com")] * 4 + [("succeed", "owner@example.com")]
    results = asyncio.run(_run(steps + [("acquire", "owner@example.com")] * 6))

    assert results[:4] == [None] * 4
    assert results[4:9] == [None] * 5
    assert results[9] is not None
