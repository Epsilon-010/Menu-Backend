import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from app.worker import purge_refresh_tokens_now
from tests.integration.modules.auth.test_auth_api import _seed


async def _add_tokens(tenant: SeedResult, expiries: dict[str, datetime]) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            for name, expires_at in expiries.items():
                session.add(
                    RefreshTokenModel(
                        tenant_id=tenant.tenant_id,
                        user_id=tenant.user_id,
                        family_id=uuid.uuid4(),
                        token_hash=name.ljust(64, "0"),
                        expires_at=expires_at,
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()


async def _remaining() -> set[str]:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            hashes = await session.scalars(select(RefreshTokenModel.token_hash))
            return {value.rstrip("0") for value in hashes}
    finally:
        await engine.dispose()


def test_the_daily_purge_drops_only_long_expired_tokens() -> None:
    tenant = asyncio.run(_seed("La Taquería", "owner@example.com"))
    now = datetime.now(UTC)
    asyncio.run(
        _add_tokens(
            tenant,
            {"gone": now - timedelta(days=3), "recent": now - timedelta(hours=2), "live": now + timedelta(days=6)},
        )
    )

    assert asyncio.run(purge_refresh_tokens_now()) == 1
    assert asyncio.run(_remaining()) == {"recent", "live"}
