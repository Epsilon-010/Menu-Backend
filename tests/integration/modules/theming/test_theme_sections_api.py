"""Menu sections (S3, S4): the admin builds the menu page from sections; tables see it only after publishing."""

import copy
import uuid
from collections.abc import Callable

import pytest

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import ClientFactory, admin_of, ok
from tests.integration.modules.tables.test_tables_api import create_table, created, tablet_of
from tests.integration.modules.theming.test_theme_api import (  # noqa: F401 (fixtures)
    PUBLISH_URL,
    THEME_URL,
    Json,
    draft_of,
    images,
    new_client,
    save,
    tenant_a,
    tenant_b,
)

IMPORT_URL = f"{THEME_URL}/import"
DEFAULT_PAGE = [
    {"id": "00000000-0000-4000-8000-000000000001", "type": "hero"},
    {"id": "00000000-0000-4000-8000-000000000002", "type": "menu"},
]
ITEM = "0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f87"


def designed(doc: Json) -> Json:
    doc["layout"]["sections"] = [
        {"id": str(uuid.uuid4()), "type": "text", "title": "Bienvenidos", "body": "Pide desde tu mesa", "align": "center",
         "style": "highlight"},
        DEFAULT_PAGE[0],
        {"id": str(uuid.uuid4()), "type": "featured", "title": "Lo más pedido", "item_ids": [ITEM], "view": "carousel"},
        {"id": str(uuid.uuid4()), "type": "divider"},
        DEFAULT_PAGE[1],
    ]
    return doc


def test_the_draft_and_every_template_start_with_the_header_then_the_menu(
    new_client: ClientFactory, tenant_a: SeedResult  # noqa: F811
) -> None:
    response = draft_of(admin_of(new_client))
    assert response["draft"]["layout"]["sections"] == DEFAULT_PAGE
    for preset in response["presets"]:
        assert [section["type"] for section in preset["layout"]["sections"]].count("menu") == 1


def test_admin_builds_the_page_and_tables_see_it_only_after_publishing(
    new_client: ClientFactory, tenant_a: SeedResult  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    tablet = tablet_of(new_client, created(create_table(admin)))
    doc = designed(draft_of(admin)["draft"])
    assert ok(save(admin, doc))["draft"] == doc

    assert ok(tablet.get(THEME_URL))["theme"]["layout"]["sections"] == DEFAULT_PAGE
    ok(admin.post(PUBLISH_URL))
    assert ok(tablet.get(THEME_URL))["theme"] == doc
    assert ok(admin.post(IMPORT_URL, json=doc))["theme"] == doc


def remove_menu(doc: Json) -> None:
    doc["layout"]["sections"] = [DEFAULT_PAGE[0]]


def unknown_type(doc: Json) -> None:
    doc["layout"]["sections"].append({"id": str(uuid.uuid4()), "type": "SECRETVAL"})


def long_title(doc: Json) -> None:
    doc["layout"]["sections"].append(
        {"id": str(uuid.uuid4()), "type": "featured", "title": "x" * 61, "item_ids": [], "view": "grid"}
    )


def extra_field(doc: Json) -> None:
    doc["layout"]["sections"].append({"id": str(uuid.uuid4()), "type": "divider", "color": "SECRETVAL"})


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        (remove_menu, "Invalid theme value: layout.sections"),
        (long_title, "Invalid theme value: layout.sections.2.title"),
    ],
)
def test_an_invalid_page_is_rejected_naming_the_field(
    new_client: ClientFactory, tenant_a: SeedResult, change: Callable[[Json], None], detail: str  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    before = draft_of(admin)["draft"]
    doc = copy.deepcopy(before)
    change(doc)
    response = save(admin, doc)
    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert draft_of(admin)["draft"] == before


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        (unknown_type, "Invalid theme value: layout.sections.2.type"),
        (extra_field, "Invalid theme value: layout.sections.2.color"),
    ],
)
def test_an_unknown_section_or_field_is_a_422_naming_the_place_without_echoing_what_was_sent(
    new_client: ClientFactory, tenant_a: SeedResult, change: Callable[[Json], None], detail: str  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    change(doc)
    for response in (save(admin, doc), admin.post(IMPORT_URL, json=doc)):
        assert response.status_code == 422
        assert response.json()["detail"].startswith(detail)
        assert "SECRETVAL" not in response.text


def test_tables_cannot_change_the_page_and_tenants_never_see_each_other(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult  # noqa: F811
) -> None:
    owner_a = admin_of(new_client)
    owner_b = admin_of(new_client, "boss@example.com")
    tablet_a = tablet_of(new_client, created(create_table(owner_a)))
    tablet_b = tablet_of(new_client, created(create_table(owner_b)))
    doc = designed(draft_of(owner_a)["draft"])
    assert save(tablet_a, doc).status_code == 403
    assert draft_of(owner_a)["draft"]["layout"]["sections"] == DEFAULT_PAGE

    ok(save(owner_a, doc))
    ok(owner_a.post(PUBLISH_URL))
    assert ok(tablet_a.get(THEME_URL))["theme"]["layout"]["sections"] == doc["layout"]["sections"]
    assert draft_of(owner_b)["draft"]["layout"]["sections"] == DEFAULT_PAGE
    assert ok(tablet_b.get(THEME_URL))["theme"]["layout"]["sections"] == DEFAULT_PAGE
