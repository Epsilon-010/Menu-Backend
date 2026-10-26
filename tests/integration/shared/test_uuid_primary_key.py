import asyncio
import uuid

from sqlalchemy import String, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import UUIDPrimaryKey


class _ProbeBase(DeclarativeBase):
    """Isolated metadata so the probe table never reaches the app's migrations."""


class _Probe(UUIDPrimaryKey, _ProbeBase):
    __tablename__ = "uuid_pk_probe"

    name: Mapped[str] = mapped_column(String(20))


async def _run(check: str) -> uuid.UUID:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_ProbeBase.metadata.create_all)
            if check == "orm":
                result = await conn.execute(insert(_Probe).values(name="orm").returning(_Probe.id))
            else:
                result = await conn.execute(text("INSERT INTO uuid_pk_probe (name) VALUES ('sql') RETURNING id"))
            generated = result.scalar_one()
            stored = (await conn.execute(select(_Probe.id).where(_Probe.id == generated))).scalar_one()
            await conn.run_sync(_ProbeBase.metadata.drop_all)
        return stored
    finally:
        await engine.dispose()


def test_python_inserts_get_an_auto_generated_uuid() -> None:
    assert isinstance(asyncio.run(_run("orm")), uuid.UUID)


def test_raw_sql_inserts_get_a_uuid_from_the_database_default() -> None:
    assert isinstance(asyncio.run(_run("sql")), uuid.UUID)


def test_new_instances_have_distinct_uuids_before_flush() -> None:
    first, second = _Probe(name="a"), _Probe(name="b")

    assert isinstance(first.id, uuid.UUID)
    assert first.id != second.id
