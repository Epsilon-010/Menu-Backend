"""The data migration that puts the badges back above the name on cards still using the first default block order."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config

from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import _seed
from tests.integration.modules.theming.test_typography_migration import (
    Json,
    at_head_afterwards,  # noqa: F401 (fixture)
    run,
    stored,
)
from tests.integration.modules.theming.test_blocks_migration import v4


BLOCKS = "b7e3a91c4d52"
BADGES_FIRST = "e2a6c0b9d817"

FIRST_DEFAULT = ["image", "heading", "description", "badges", "add_button"]
BADGES_ABOVE_NAME = ["image", "badges", "heading", "description", "add_button"]
CHOSEN = ["add_button", "description", "heading", "badges", "image"]


def with_blocks(doc: Json, blocks: list[str]) -> Json:
    changed = json.loads(json.dumps(doc))
    changed["cards"]["blocks"] = blocks
    return changed


def insert(tenant_id: uuid.UUID, draft: Json, published: Json, version: Json) -> None:
    run(
        "INSERT INTO themes (id, tenant_id, draft, published) "
        "VALUES (:id, :tenant, CAST(:draft AS jsonb), CAST(:published AS jsonb))",
        id=uuid.uuid4(),
        tenant=tenant_id,
        draft=json.dumps(draft),
        published=json.dumps(published),
    )
    run(
        "INSERT INTO theme_versions (id, tenant_id, number, theme, published_at) "
        "VALUES (:id, :tenant, 1, CAST(:theme AS jsonb), :at)",
        id=uuid.uuid4(),
        tenant=tenant_id,
        theme=json.dumps(version),
        at=datetime(2026, 11, 4, tzinfo=UTC),
    )


def versions(tenant_id: uuid.UUID) -> list[Json]:
    return [theme for (theme,) in run("SELECT theme FROM theme_versions WHERE tenant_id = :tenant", tenant=tenant_id)]


def test_cards_on_the_first_default_order_get_the_badges_above_the_name_and_chosen_orders_stay(
    at_head_afterwards: Config,  # noqa: F811
) -> None:
    tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    command.downgrade(at_head_afterwards, BLOCKS)
    run("DELETE FROM theme_versions WHERE tenant_id = :tenant", tenant=tenant.tenant_id)
    run("DELETE FROM themes WHERE tenant_id = :tenant", tenant=tenant.tenant_id)
    base = v4("#111111", "vertical")
    base["schema_version"] = 5
    base["layout"]["header_blocks"] = ["banner", "name", "tagline", "welcome"]
    base["layout"]["categories"] = {}
    insert(
        tenant.tenant_id,
        with_blocks(base, FIRST_DEFAULT),
        with_blocks(base, CHOSEN),
        with_blocks(base, FIRST_DEFAULT),
    )

    command.upgrade(at_head_afterwards, BADGES_FIRST)

    draft, published = stored(tenant.tenant_id)
    assert draft["cards"]["blocks"] == BADGES_ABOVE_NAME
    assert published is not None and published["cards"]["blocks"] == CHOSEN
    assert all(version["cards"]["blocks"] == BADGES_ABOVE_NAME for version in versions(tenant.tenant_id))
    # Nothing else in the documents moves.
    assert with_blocks(draft, FIRST_DEFAULT) == with_blocks(base, FIRST_DEFAULT)

    command.downgrade(at_head_afterwards, BLOCKS)

    draft, published = stored(tenant.tenant_id)
    assert draft["cards"]["blocks"] == FIRST_DEFAULT
    assert published is not None and published["cards"]["blocks"] == CHOSEN
