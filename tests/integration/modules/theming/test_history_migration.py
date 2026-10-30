"""The migration that creates the history of published themes, seeded with what each tenant publishes today."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config

from app.modules.theming.domain.theme import default_theme
from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import _seed
from tests.integration.modules.theming.test_typography_migration import (
    at_head_afterwards,  # noqa: F401 (fixture)
    run,
    stored,
)

BEFORE_HISTORY = "e9475ed1ea8b"


def test_each_published_theme_becomes_version_1_and_downgrade_drops_the_history(at_head_afterwards: Config) -> None:  # noqa: F811
    published_tenant: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    draft_only: SeedResult = asyncio.run(_seed("Burger Place", "boss@example.com"))
    command.downgrade(at_head_afterwards, BEFORE_HISTORY)

    draft = default_theme().to_dict()
    published = default_theme().to_dict()
    published["colors"]["primary"] = "#222222"
    published_at = datetime(2026, 10, 29, 18, 30, tzinfo=UTC)
    insert = (
        "INSERT INTO themes (id, tenant_id, draft, published, published_at) "
        "VALUES (:id, :tenant, CAST(:draft AS jsonb), {}, :published_at)"
    )
    run(
        insert.format("CAST(:published AS jsonb)"),
        id=uuid.uuid4(),
        tenant=published_tenant.tenant_id,
        draft=json.dumps(draft),
        published=json.dumps(published),
        published_at=published_at,
    )
    run(insert.format("NULL"), id=uuid.uuid4(), tenant=draft_only.tenant_id, draft=json.dumps(draft), published_at=None)

    command.upgrade(at_head_afterwards, "head")

    versions = run("SELECT tenant_id, number, theme, published_at FROM theme_versions")
    assert versions == [(published_tenant.tenant_id, 1, published, published_at)]
    assert stored(published_tenant.tenant_id) == (draft, published)  # the themes stay as they were

    command.downgrade(at_head_afterwards, BEFORE_HISTORY)
    assert run("SELECT to_regclass('theme_versions')") == [(None,)]
    assert stored(published_tenant.tenant_id) == (draft, published)
