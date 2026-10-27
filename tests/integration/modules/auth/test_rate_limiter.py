import asyncio

from redis.asyncio import Redis

from app.modules.auth.infrastructure.rate_limiter import RedisLoginAttemptLimiter
from app.shared.infrastructure.config import get_settings


async def _concurrent_attempts(attempts: int, max_per_account: int, max_per_ip: int, same_ip: bool) -> list[int | None]:
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        limiter = RedisLoginAttemptLimiter(redis, window_seconds=900, max_per_account=max_per_account, max_per_ip=max_per_ip)
        return await asyncio.gather(
            *(
                limiter.acquire("203.0.113.7" if same_ip else f"203.0.113.{n}", "owner@example.com")
                for n in range(attempts)
            )
        )
    finally:
        await redis.aclose()


def test_parallel_attempts_never_exceed_the_account_limit() -> None:
    results = asyncio.run(_concurrent_attempts(30, max_per_account=5, max_per_ip=1000, same_ip=False))

    assert results.count(None) == 5
    assert all(0 < wait <= 900 for wait in results if wait is not None)


def test_parallel_attempts_never_exceed_the_ip_limit() -> None:
    results = asyncio.run(_concurrent_attempts(30, max_per_account=1000, max_per_ip=20, same_ip=True))

    assert results.count(None) == 20


async def _succeed_then_retry() -> list[int | None]:
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        limiter = RedisLoginAttemptLimiter(redis, window_seconds=900, max_per_account=2, max_per_ip=2)
        first = await limiter.acquire("203.0.113.7", "owner@example.com")
        await limiter.succeeded("203.0.113.7", "owner@example.com")
        # The successful attempt was given back, so two more attempts fit in the window.
        return [first, *[await limiter.acquire("203.0.113.7", "owner@example.com") for _ in range(3)]]
    finally:
        await redis.aclose()


def test_a_successful_login_gives_its_attempt_back() -> None:
    first, *after_success = asyncio.run(_succeed_then_retry())

    assert first is None
    assert after_success[:2] == [None, None]
    assert after_success[2] is not None