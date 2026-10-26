import os

import pytest

# Test-only signing key, used when the environment does not provide one.
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-not-for-production-0001")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
