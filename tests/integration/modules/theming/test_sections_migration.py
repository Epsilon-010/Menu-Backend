"""The data migration that moves stored themes, and every saved version, to schema_version 6 (sections), and back."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config

from app.modules.theming.domain.theme import DEFAULT_SECTIONS, default_theme, parse_theme
from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import _seed
from tests.integration.modules.theming.test_blocks_migration import versions
from tests.integration.modules.theming.test_typography_migration import (
    Json,
    at_head_afterwards,  # noqa: F401 (fixture)
    run,
    stored,
)

BEFORE_SECTIONS = "de3bacf10d81"
SECTIONS = "5d0e7a3c9b14"

DEFAULT_PAGE = [
    {"id": "00000000-0000-4000-8000-000000000001", "type": "hero"},
    {"id": "00000000-0000-4000-8000-000000000002", "type": "menu"},
]


def v5(primary: str, navigation: str) -> Json:
    """A theme as UX round 2 stored it (before sections)."""
    doc = default_theme().to_dict()
    del doc["layout"]["sections"]
    doc["schema_version"] = 5
    doc["colors"]["primary"] = primary
    doc["layout"]["navigation"] = navigation
    doc["layout"]["categories"] = {str(uuid.uuid4()): {"product_view": "list", "columns": 1, "card_template": "horizontal"}}
    return doc


def as_v6(doc: Json) -> Json:
    upgraded = json.loads(json.dumps(doc))
    upgraded["schema_version"] = 6
    upgraded["layout"]["sections"] = DEFAULT_PAGE
    return upgraded


def test_stored_v5_themes_and_their_history_get_the_default_page_and_downgrade_removes_it(
    at_head_afterwards: Config,  # noqa: F811
) -> None:
    published_tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    draft_only: SeedResult = asyncio.run(_seed("Burger Place", "boss@example.com"))
    command.downgrade(at_head_afterwards, BEFORE_SECTIONS)

    draft = v5("#111111", "tabs")
    published = v5("#222222", "sidebar")
    first_version = v5("#333333", "chips")
    lone_draft = v5("#444444", "sections")
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

    command.upgrade(at_head_afterwards, SECTIONS)

    assert stored(published_tenant.tenant_id) == (as_v6(draft), as_v6(published))
    assert stored(draft_only.tenant_id) == (as_v6(lone_draft), None)
    assert versions(published_tenant.tenant_id) == [as_v6(first_version), as_v6(published)]
    for doc in (*stored(published_tenant.tenant_id), *versions(published_tenant.tenant_id)):
        assert doc is not None
        assert parse_theme(doc, published_tenant.tenant_id).layout.sections == DEFAULT_SECTIONS

    command.downgrade(at_head_afterwards, BEFORE_SECTIONS)
    assert stored(published_tenant.tenant_id) == (draft, published)
    assert stored(draft_only.tenant_id) == (lone_draft, None)
    assert versions(published_tenant.tenant_id) == [first_version, published]

    command.upgrade(at_head_afterwards, SECTIONS)
    assert stored(published_tenant.tenant_id) == (as_v6(draft), as_v6(published))


def test_the_downgrade_drops_the_sections_an_admin_added(at_head_afterwards: Config) -> None:  # noqa: F811
    tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    designed = default_theme().to_dict()
    designed["layout"]["sections"] = [
        {"id": str(uuid.uuid4()), "type": "text", "title": "Hola", "body": "", "align": "center", "style": "plain"},
        *DEFAULT_PAGE,
    ]
    run(
        "INSERT INTO themes (id, tenant_id, draft, published) VALUES (:id, :tenant, CAST(:draft AS jsonb), NULL)",
        id=uuid.uuid4(),
        tenant=tenant.tenant_id,
        draft=json.dumps(designed),
    )

    command.downgrade(at_head_afterwards, BEFORE_SECTIONS)
    expected = default_theme().to_dict()
    del expected["layout"]["sections"]
    expected["schema_version"] = 5
    assert stored(tenant.tenant_id) == (expected, None)
