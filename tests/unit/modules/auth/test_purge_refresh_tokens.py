import uuid
from datetime import timedelta

import pytest

from app.modules.auth.application.purge_refresh_tokens import PurgeExpiredRefreshTokens
from app.modules.auth.domain.refresh_token import RefreshToken
from tests.unit.fakes import FakeClock, FakeUnitOfWork, InMemoryRefreshTokenRepository

pytestmark = pytest.mark.anyio

TENANT = uuid.uuid4()


def _token(clock: FakeClock, expires_in: timedelta, **state: object) -> RefreshToken:
    return RefreshToken(
        tenant_id=TENANT,
        user_id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        token_hash=uuid.uuid4().hex,
        created_at=clock.now() - timedelta(days=30),
        expires_at=clock.now() + expires_in,
        **state,  # type: ignore[arg-type]
    )


async def test_purges_only_tokens_expired_for_longer_than_the_grace_period() -> None:
    clock = FakeClock()
    tokens = InMemoryRefreshTokenRepository()
    long_gone = _token(clock, -timedelta(days=2))
    just_expired = _token(clock, -timedelta(hours=1))
    # Rotated but still valid: kept, it is what detects the reuse of a stolen token.
    rotated = _token(clock, timedelta(days=3), rotated_at=clock.now())
    active = _token(clock, timedelta(days=7))
    for token in (long_gone, just_expired, rotated, active):
        await tokens.add(token)
    uow = FakeUnitOfWork()

    purged = await PurgeExpiredRefreshTokens(tokens, clock, uow, grace=timedelta(days=1)).execute()

    assert purged == 1
    assert set(tokens.tokens) == {just_expired.id, rotated.id, active.id}
    assert uow.commits == 1
