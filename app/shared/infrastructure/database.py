import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy import MetaData, Uuid, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every module's SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    """Mixin for every table: auto-generated UUID primary key.

    The id is assigned on construction (stdlib uuid4) and Postgres also defaults it with
    gen_random_uuid(), so rows inserted outside the ORM get one too.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        super().__init__(**kwargs)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def violated_unique_constraint(error: IntegrityError) -> str | None:
    """Name of the unique constraint or index a failed write broke, or None for any other integrity error.

    Use cases check uniqueness first, but two concurrent requests can both pass that check; the
    database index is what keeps the data right, and the repository turns its name into the
    matching domain error.
    """
    cause = _driver_error(error)
    if getattr(cause, "sqlstate", None) != "23505":  # unique_violation
        return None
    name = getattr(cause, "constraint_name", None)
    return name if isinstance(name, str) else None


async def advisory_xact_lock(session: AsyncSession, key: str) -> None:
    """Postgres lock on `key` held until the transaction ends.

    For work that must not interleave but has no single row to lock: positions computed as max + 1,
    or the replay check of an idempotent create that runs before its row exists.
    """
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


def affected_rows(result: Any) -> int:
    """Rows an UPDATE or DELETE touched: 0 means the row is gone (or never matched the tenant).

    Repositories turn 0 into the module's not-found error instead of reporting a silent success.
    """
    return int(getattr(result, "rowcount", 0) or 0)


def violated_foreign_key(error: IntegrityError) -> str | None:
    """Name of the foreign key a failed write broke (e.g. deleting a row others still reference)."""
    cause = _driver_error(error)
    if getattr(cause, "sqlstate", None) != "23503":  # foreign_key_violation
        return None
    name = getattr(cause, "constraint_name", None)
    return name if isinstance(name, str) else None


def _driver_error(error: IntegrityError) -> BaseException | None:
    # SQLAlchemy wraps asyncpg's error in an adapter exception; the original is its cause.
    return error.orig.__cause__ if error.orig is not None else None


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()


class PostgresProbe:
    name = "postgres"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def is_healthy(self) -> bool:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
