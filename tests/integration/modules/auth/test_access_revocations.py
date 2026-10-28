import uuid

import pytest
from redis.asyncio import Redis

from app.modules.auth.infrastructure.access_revocations import RedisAccessRevocations
from app.shared.infrastructure.config import get_settings

pytestmark = pytest.mark.anyio


async def test_records_the_required_session_version_for_one_access_lifetime() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    revocations = RedisAccessRevocations(redis)
    subject, other = uuid.uuid4(), uuid.uuid4()
    try:
        await revocations.require_version(subject, 2)

        assert await revocations.required_version(subject) == 2
        assert await revocations.required_version(other) is None
        assert 900 < await redis.ttl(f"auth:session-version:{subject}") <= 960
    finally:
        await redis.aclose()


async def test_changes_finishing_out_of_order_never_lower_the_required_version() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    revocations = RedisAccessRevocations(redis)
    subject = uuid.uuid4()
    try:
        await revocations.require_version(subject, 3)
        await revocations.require_version(subject, 2)

        assert await revocations.required_version(subject) == 3
    finally:
        await redis.aclose()


async def test_a_redis_outage_fails_open() -> None:
    # Nothing listens on port 1: every command raises a connection error.
    redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    revocations = RedisAccessRevocations(redis)
    try:
        await revocations.require_version(uuid.uuid4(), 2)

        assert await revocations.required_version(uuid.uuid4()) is None
    finally:
        await redis.aclose()
