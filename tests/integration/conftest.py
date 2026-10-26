"""Integration fixtures: a dedicated test database built with Alembic migrations.

The test database is `<DATABASE_URL db name>_test` and the test Redis uses logical db 15,
so running the suite never touches development data.
"""

import asyncio
import os
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine


def _derive_test_urls() -> tuple[str, str]:
    # Read the regular settings first, then point the process at the test resources.
    from app.shared.infrastructure.config import get_settings

    settings = get_settings()
    db_url = make_url(settings.database_url)
    test_db_url = db_url.set(database=f"{db_url.database}_test")
    test_redis_url = urlsplit(settings.redis_url)._replace(path="/15").geturl()
    return test_db_url.render_as_string(hide_password=False), test_redis_url


TEST_DATABASE_URL, TEST_REDIS_URL = _derive_test_urls()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL

from app.shared.infrastructure.config import get_settings  # noqa: E402

get_settings.cache_clear()


async def _recreate_database(url: str) -> None:
    target = make_url(url)
    admin_engine = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    await admin_engine.dispose()


async def _truncate_tables(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        tables = [f'"{name}"' for name in result.scalars()]
        if tables:
            await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    from alembic import command
    from alembic.config import Config

    asyncio.run(_recreate_database(TEST_DATABASE_URL))
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture(autouse=True)
def clean_database(migrated_database: None) -> Iterator[None]:
    yield
    asyncio.run(_truncate_tables(TEST_DATABASE_URL))


@pytest.fixture(autouse=True)
def clean_redis() -> Iterator[None]:
    yield
    with Redis.from_url(TEST_REDIS_URL) as redis:
        redis.flushdb()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    # HTTPS so the client cookie jar sends back the Secure refresh cookie.
    with TestClient(create_app(), base_url="https://testserver") as test_client:
        yield test_client
