import uuid
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis

from app.modules.auth.infrastructure.access_revocations import RedisAccessRevocations
from app.shared.infrastructure.config import get_settings

pytestmark = pytest.mark.anyio


async def test_records_the_revocation_time_with_sub_second_precision_for_one_access_lifetime() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    revocations = RedisAccessRevocations(redis)
    subject, other = uuid.uuid4(), uuid.uuid4()
    at = datetime(2026, 10, 27, 9, 30, 15, 123456, tzinfo=UTC)
    try:
        await revocations.revoke(subject, at)

        assert await revocations.revoked_since(subject) == at
        assert await revocations.revoked_since(other) is None
        assert 900 < await redis.ttl(f"auth:revoked:{subject}") <= 960
    finally:
        await redis.aclose()


async def test_a_redis_outage_fails_open() -> None:
    # Nothing listens on port 1: every command raises a connection error.
    redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    revocations = RedisAccessRevocations(redis)
    try:
        await revocations.revoke(uuid.uuid4(), datetime.now(UTC))

        assert await revocations.revoked_since(uuid.uuid4()) is None
    finally:
        await redis.aclose()
