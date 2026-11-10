"""The data migration that moves stored themes, and every saved version, to schema_version 5 (blocks), and back."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config

from app.modules.theming.domain.import_theme import import_theme
from app.modules.theming.domain.theme import Theme, default_theme
from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import _seed
from tests.integration.modules.theming.test_typography_migration import (
    Json,
    at_head_afterwards,  # noqa: F401 (fixture)
    run,
    stored,
    v4_document,
)

BEFORE_BLOCKS = "548bab5f5d29"
BLOCKS = "b7e3a91c4d52"

CARD_BLOCKS = ["image", "heading", "description", "badges", "add_button"]
HEADER_BLOCKS = ["banner", "name", "tagline", "welcome"]


def v4(primary: str, template: str) -> Json:
    """A theme as Slices 13-17 stored it."""
    doc = v4_document()
    doc["colors"]["primary"] = primary
    doc["cards"]["template"] = template
    return doc


def versions(tenant_id: uuid.UUID) -> list[Json]:
    rows = run("SELECT theme FROM theme_versions WHERE tenant_id = :tenant ORDER BY number", tenant=tenant_id)
    return [theme for (theme,) in rows]


def read_v5(doc: Json, tenant_id: uuid.UUID) -> Theme:
    """A stored version 5 document as the app reads it once upgraded (fails unless it is a valid version 5)."""
    assert doc["schema_version"] == 5
    return import_theme(doc, tenant_id, set()).theme


def as_v5(doc: Json) -> Json:
    """What the upgrade must turn that v4 document into: the same values plus the default blocks."""
    upgraded = json.loads(json.dumps(doc))
    upgraded["schema_version"] = 5
    upgraded["cards"]["blocks"] = CARD_BLOCKS
    upgraded["layout"]["header_blocks"] = HEADER_BLOCKS
    upgraded["layout"]["categories"] = {}
    return upgraded


def test_stored_v4_themes_and_their_history_get_the_default_blocks_and_downgrade_removes_them(
    at_head_afterwards: Config,  # noqa: F811
) -> None:
    published_tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    draft_only: SeedResult = asyncio.run(_seed("Burger Place", "boss@example.com"))
    command.downgrade(at_head_afterwards, BEFORE_BLOCKS)

    draft = v4("#111111", "overlay")
    published = v4("#222222", "horizontal")
    first_version = v4("#333333", "vertical")
    lone_draft = v4("#444444", "horizontal")
    insert = "INSERT INTO themes (id, tenant_id, draft, published) VALUES (:id, :tenant, CAST(:draft AS jsonb), {})"
    run(
        insert.format("CAST(:published AS jsonb)"),
        id=uuid.uuid4(),
        tenant=published_tenant.tenant_id,
        draft=json.dumps(draft),
        published=json.dumps(published),
    )
    run(insert.format("NULL"), id=uuid.uuid4(), tenant=draft_only.tenant_id, draft=json.dumps(lone_draft))
    for number, theme in ((1, first_version), (2, published)):
        run(
            "INSERT INTO theme_versions (id, tenant_id, number, theme, published_at) "
            "VALUES (:id, :tenant, :number, CAST(:theme AS jsonb), :at)",
            id=uuid.uuid4(),
            tenant=published_tenant.tenant_id,
            number=number,
            theme=json.dumps(theme),
            at=datetime(2026, 11, number, tzinfo=UTC),
        )

    command.upgrade(at_head_afterwards, BLOCKS)

    assert stored(published_tenant.tenant_id) == (as_v5(draft), as_v5(published))
    assert stored(draft_only.tenant_id) == (as_v5(lone_draft), None)
    assert versions(published_tenant.tenant_id) == [as_v5(first_version), as_v5(published)]
    # They are valid version 5 documents (read through the import, which takes them to the current version). The order
    # is the first default this migration froze; e2a6c0b9d817 then puts the badges back above the name
    # (test_badges_first_migration.py).
    for doc in (*stored(published_tenant.tenant_id), *versions(published_tenant.tenant_id)):
        assert doc is not None
        theme = read_v5(doc, published_tenant.tenant_id)
        assert theme.cards.blocks == tuple(CARD_BLOCKS)
        assert theme.layout.header_blocks == default_theme().layout.header_blocks
        assert theme.layout.categories == {}
    assert read_v5(stored(published_tenant.tenant_id)[1], published_tenant.tenant_id).cards.template == "horizontal"

    command.downgrade(at_head_afterwards, BEFORE_BLOCKS)
    assert stored(published_tenant.tenant_id) == (draft, published)
    assert stored(draft_only.tenant_id) == (lone_draft, None)
    assert versions(published_tenant.tenant_id) == [first_version, published]

    command.upgrade(at_head_afterwards, BLOCKS)
    assert stored(published_tenant.tenant_id) == (as_v5(draft), as_v5(published))
    assert versions(published_tenant.tenant_id) == [as_v5(first_version), as_v5(published)]


def test_the_downgrade_drops_the_block_order_and_category_layouts_an_admin_set(
    at_head_afterwards: Config,  # noqa: F811
) -> None:
    tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    designed = default_theme().to_dict()
    designed["cards"]["blocks"] = list(reversed(CARD_BLOCKS))
    designed["layout"]["header_blocks"] = list(reversed(HEADER_BLOCKS))
    designed["layout"]["categories"] = {
        str(uuid.uuid4()): {"product_view": "list", "columns": 1, "card_template": "horizontal"}
    }
    run(
        "INSERT INTO themes (id, tenant_id, draft, published) VALUES (:id, :tenant, CAST(:draft AS jsonb), NULL)",
        id=uuid.uuid4(),
        tenant=tenant.tenant_id,
        draft=json.dumps(designed),
    )

    command.downgrade(at_head_afterwards, BEFORE_BLOCKS)
    assert stored(tenant.tenant_id) == (v4_document(), None)
