"""The data migration that moves stored themes to schema_version 4 (cards), and back."""

import asyncio
import json
import uuid
from typing import Any

from alembic import command
from alembic.config import Config

from app.modules.theming.domain.theme import default_theme, parse_theme
from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import _seed
from tests.integration.modules.theming.test_layout_migration import WITH_LAYOUT
from tests.integration.modules.theming.test_typography_migration import (
    at_head_afterwards,  # noqa: F401 (fixture)
    run,
    stored,
)

Json = dict[str, Any]


def v3_document(primary: str, navigation: str) -> Json:
    """A theme as Slice 12 stored it."""
    doc = default_theme().to_dict()
    del doc["cards"]
    doc["schema_version"] = 3
    doc["colors"]["primary"] = primary
    doc["layout"]["navigation"] = navigation
    return doc


def test_stored_v3_themes_get_the_default_cards_and_downgrade_removes_them(at_head_afterwards: Config) -> None:  # noqa: F811
    published_tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    draft_only: SeedResult = asyncio.run(_seed("Burger Place", "boss@example.com"))
    command.downgrade(at_head_afterwards, WITH_LAYOUT)

    draft = v3_document("#111111", "tabs")
    published = v3_document("#222222", "sidebar")
    lone_draft = v3_document("#333333", "sections")
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

    default_cards = default_theme().to_dict()["cards"]
    upgraded_draft, upgraded_published = stored(published_tenant.tenant_id)
    assert upgraded_published is not None
    for doc, original in ((upgraded_draft, draft), (upgraded_published, published), (stored(draft_only.tenant_id)[0], lone_draft)):
        assert doc["schema_version"] == 4
        assert doc["cards"] == default_cards
        # Everything else stays exactly as the admin left it.
        assert {key: value for key, value in doc.items() if key not in ("cards", "schema_version")} == {
            key: value for key, value in original.items() if key != "schema_version"
        }
    assert parse_theme(upgraded_draft, published_tenant.tenant_id).layout.navigation == "tabs"
    assert parse_theme(upgraded_published, published_tenant.tenant_id).colors.primary == "#222222"
    assert stored(draft_only.tenant_id)[1] is None

    command.downgrade(at_head_afterwards, WITH_LAYOUT)
    assert stored(published_tenant.tenant_id) == (draft, published)
    assert stored(draft_only.tenant_id) == (lone_draft, None)


def test_the_upgrade_leaves_documents_already_at_version_4_untouched(at_head_afterwards: Config) -> None:  # noqa: F811
    tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    current = default_theme().to_dict()
    current["cards"]["template"] = "overlay"
    run(
        "INSERT INTO themes (id, tenant_id, draft, published) VALUES (:id, :tenant, CAST(:draft AS jsonb), NULL)",
        id=uuid.uuid4(),
        tenant=tenant.tenant_id,
        draft=json.dumps(current),
    )
    # Going down only touches version 4 documents, so step back first and re-store the v4 one, then upgrade.
    command.downgrade(at_head_afterwards, WITH_LAYOUT)
    run("UPDATE themes SET draft = CAST(:draft AS jsonb) WHERE tenant_id = :tenant", tenant=tenant.tenant_id, draft=json.dumps(current))
    command.upgrade(at_head_afterwards, "head")
    assert stored(tenant.tenant_id) == (current, None)
