"""The data migration that moves stored themes to schema_version 3 (layout), and back."""

import asyncio
import json
import uuid
from typing import Any

from alembic.config import Config
from alembic import command

from app.modules.theming.domain.theme import default_theme, parse_theme
from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import _seed
from tests.integration.modules.theming.test_typography_migration import (
    WITH_TYPOGRAPHY,
    at_head_afterwards,  # noqa: F401 (fixture)
    run,
    stored,
)

Json = dict[str, Any]


def v2_document(primary: str, heading_font: str) -> Json:
    """A theme as Slice 11 stored it."""
    doc = default_theme().to_dict()
    del doc["layout"]
    doc["schema_version"] = 2
    doc["colors"]["primary"] = primary
    doc["typography"]["fonts"]["heading"] = heading_font
    return doc


def test_stored_v2_themes_get_the_default_layout_and_downgrade_removes_it(at_head_afterwards: Config) -> None:  # noqa: F811
    published_tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    draft_only: SeedResult = asyncio.run(_seed("Burger Place", "boss@example.com"))
    command.downgrade(at_head_afterwards, WITH_TYPOGRAPHY)

    draft = v2_document("#111111", "lora")
    published = v2_document("#222222", "oswald")
    lone_draft = v2_document("#333333", "geist")
    insert = "INSERT INTO themes (id, tenant_id, draft, published) VALUES (:id, :tenant, CAST(:draft AS jsonb), {})"
    run(
        insert.format("CAST(:published AS jsonb)"),
        id=uuid.uuid4(),
        tenant=published_tenant.tenant_id,
        draft=json.dumps(draft),
        published=json.dumps(published),
    )
    run(insert.format("NULL"), id=uuid.uuid4(), tenant=draft_only.tenant_id, draft=json.dumps(lone_draft))

    command.upgrade(at_head_afterwards, "head")

    default_layout = default_theme().to_dict()["layout"]
    upgraded_draft, upgraded_published = stored(published_tenant.tenant_id)
    assert upgraded_published is not None
    for doc, original in ((upgraded_draft, draft), (upgraded_published, published), (stored(draft_only.tenant_id)[0], lone_draft)):
        assert doc["schema_version"] == 3
        assert doc["layout"] == default_layout
        # Everything else stays exactly as the admin left it.
        assert {key: value for key, value in doc.items() if key not in ("layout", "schema_version")} == {
            key: value for key, value in original.items() if key != "schema_version"
        }
    assert parse_theme(upgraded_draft, published_tenant.tenant_id).typography.fonts.heading == "lora"
    assert parse_theme(upgraded_published, published_tenant.tenant_id).colors.primary == "#222222"
    assert stored(draft_only.tenant_id)[1] is None

    command.downgrade(at_head_afterwards, WITH_TYPOGRAPHY)
    assert stored(published_tenant.tenant_id) == (draft, published)
    assert stored(draft_only.tenant_id) == (lone_draft, None)


def test_the_upgrade_leaves_documents_already_at_version_3_untouched(at_head_afterwards: Config) -> None:  # noqa: F811
    tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    command.downgrade(at_head_afterwards, WITH_TYPOGRAPHY)
    current = default_theme().to_dict()
    current["layout"]["navigation"] = "tabs"
    run(
        "INSERT INTO themes (id, tenant_id, draft, published) VALUES (:id, :tenant, CAST(:draft AS jsonb), NULL)",
        id=uuid.uuid4(),
        tenant=tenant.tenant_id,
        draft=json.dumps(current),
    )
    command.upgrade(at_head_afterwards, "head")
    assert stored(tenant.tenant_id) == (current, None)
