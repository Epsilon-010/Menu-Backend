"""The data migration that moves stored themes to schema_version 2 (typography), and back."""

import asyncio
import copy
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.theming.domain.theme import default_theme
from app.seed import SeedResult
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.modules.auth.test_auth_api import _seed

BEFORE_TYPOGRAPHY = "744ab3c2ac86"
WITH_TYPOGRAPHY = "3f7686d2fe3f"

Json = dict[str, Any]


def v1_document(logo_position: str, primary: str) -> Json:
    """A theme as Slice 10 stored it."""
    doc = default_theme().to_dict()
    del doc["typography"]
    del doc["layout"]
    doc["schema_version"] = 1
    doc["brand"]["logo"]["position"] = logo_position
    doc["colors"]["primary"] = primary
    return doc


async def _execute(statement: str, **params: Any) -> list[Any]:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), params)
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


def run(statement: str, **params: Any) -> list[Any]:
    return asyncio.run(_execute(statement, **params))


@pytest.fixture
def at_head_afterwards() -> Iterator[Config]:
    config = Config("alembic.ini")
    try:
        yield config
    finally:
        command.upgrade(config, "head")


def stored(tenant_id: uuid.UUID) -> tuple[Json, Json | None]:
    [(draft, published)] = run("SELECT draft, published FROM themes WHERE tenant_id = :tenant", tenant=tenant_id)
    return draft, published


def test_stored_v1_themes_get_the_default_typography_and_downgrade_removes_it(at_head_afterwards: Config) -> None:
    centered: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    left: SeedResult = asyncio.run(_seed("Burger Place", "boss@example.com"))
    command.downgrade(at_head_afterwards, BEFORE_TYPOGRAPHY)

    draft_centered = v1_document("center", "#111111")
    published_centered = v1_document("center", "#222222")
    draft_left = v1_document("left", "#333333")
    insert = "INSERT INTO themes (id, tenant_id, draft, published) VALUES (:id, :tenant, CAST(:draft AS jsonb), {})"
    run(
        insert.format("CAST(:published AS jsonb)"),
        id=uuid.uuid4(),
        tenant=centered.tenant_id,
        draft=json.dumps(draft_centered),
        published=json.dumps(published_centered),
    )
    run(insert.format("NULL"), id=uuid.uuid4(), tenant=left.tenant_id, draft=json.dumps(draft_left))

    command.upgrade(at_head_afterwards, WITH_TYPOGRAPHY)

    draft, published = stored(centered.tenant_id)
    assert published is not None
    defaults = default_theme().to_dict()["typography"]
    for doc, original in ((draft, draft_centered), (published, published_centered)):
        assert doc["schema_version"] == 2
        assert doc["typography"] == defaults
        assert {key: value for key, value in doc.items() if key not in ("typography", "schema_version")} == {
            key: value for key, value in original.items() if key != "schema_version"
        }

    draft, published = stored(left.tenant_id)
    assert published is None
    expected = copy.deepcopy(defaults)
    expected["elements"]["business_name"]["align"] = "left"  # the name kept following the logo
    assert draft["typography"] == expected

    command.downgrade(at_head_afterwards, BEFORE_TYPOGRAPHY)
    assert stored(centered.tenant_id) == (draft_centered, published_centered)
    assert stored(left.tenant_id) == (draft_left, None)
