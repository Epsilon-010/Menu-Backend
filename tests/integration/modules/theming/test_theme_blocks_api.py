"""UX round 2 (S4, S6): the admin drags card and header blocks and gives a category its own product view."""

import copy
import uuid

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
VERSIONS_URL = f"{THEME_URL}/versions"
BREAKFAST = "0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f87"


def designed(doc: Json) -> Json:
    doc["cards"]["blocks"] = ["heading", "description", "image", "add_button", "badges"]
    doc["layout"]["header_blocks"] = ["name", "tagline", "banner", "welcome"]
    doc["layout"]["categories"] = {BREAKFAST: {"product_view": "carousel", "columns": 3, "card_template": "overlay"}}
    return doc


def test_the_draft_starts_with_the_default_blocks_and_no_category_layouts(
    new_client: ClientFactory, tenant_a: SeedResult  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    response = draft_of(admin)
    draft = response["draft"]
    assert draft["schema_version"] == 5
    assert draft["cards"]["blocks"] == ["image", "heading", "description", "badges", "add_button"]
    assert draft["layout"]["header_blocks"] == ["banner", "name", "tagline", "welcome"]
    assert draft["layout"]["categories"] == {}
    for preset in response["presets"]:
        assert preset["cards"]["blocks"] == draft["cards"]["blocks"]
        assert preset["layout"]["header_blocks"] == draft["layout"]["header_blocks"]
        assert preset["layout"]["categories"] == {}


def test_admin_orders_the_blocks_and_designs_a_category_and_tables_see_it_only_after_publishing(
    new_client: ClientFactory, tenant_a: SeedResult  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    tablet = tablet_of(new_client, created(create_table(admin)))
    doc = designed(draft_of(admin)["draft"])
    saved = ok(save(admin, doc))["draft"]
    assert saved == doc

    assert ok(tablet.get(THEME_URL))["theme"]["layout"]["categories"] == {}
    ok(admin.post(PUBLISH_URL))
    published = ok(tablet.get(THEME_URL))["theme"]
    assert published == doc
    assert ok(admin.get(VERSIONS_URL))["versions"][0]["theme"] == doc


def test_an_uppercase_category_id_comes_back_lowercase(
    new_client: ClientFactory, tenant_a: SeedResult  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    doc["layout"]["categories"] = {BREAKFAST.upper(): {"product_view": "list", "columns": 1, "card_template": "horizontal"}}
    assert list(ok(save(admin, doc))["draft"]["layout"]["categories"]) == [BREAKFAST]


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        (lambda doc: doc["cards"].update(blocks=["image", "heading"]), "Invalid theme value: cards.blocks"),
        (
            lambda doc: doc["layout"].update(header_blocks=["banner", "name", "name", "welcome"]),
            "Invalid theme value: layout.header_blocks",
        ),
        (
            lambda doc: doc["layout"].update(categories={"breakfast": {"product_view": "list", "columns": 1, "card_template": "vertical"}}),
            "Invalid theme value: layout.categories",
        ),
        (
            lambda doc: doc["layout"].update(categories={BREAKFAST: {"product_view": "list", "columns": 9, "card_template": "vertical"}}),
            f"Invalid theme value: layout.categories.{BREAKFAST}.columns",
        ),
        (
            lambda doc: doc["layout"].update(
                categories={str(uuid.uuid4()): {"product_view": "grid", "columns": 2, "card_template": "vertical"} for _ in range(101)}
            ),
            "Invalid theme value: layout.categories",
        ),
    ],
)
def test_an_invalid_block_order_or_category_layout_is_rejected_and_nothing_changes(
    new_client: ClientFactory, tenant_a: SeedResult, change: object, detail: str  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    before = copy.deepcopy(doc)
    change(doc)  # type: ignore[operator]
    response = save(admin, doc)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == detail
    assert draft_of(admin)["draft"] == before


@pytest.mark.parametrize(
    "change",
    [
        lambda doc: doc["layout"]["categories"].update({BREAKFAST: {"product_view": "list", "columns": 1}}),
        lambda doc: doc["layout"]["categories"].update(
            {BREAKFAST: {"product_view": "list", "columns": 1, "card_template": "vertical", "css": "x"}}
        ),
        lambda doc: doc["layout"].pop("header_blocks"),
        lambda doc: doc["cards"].pop("blocks"),
    ],
)
def test_a_missing_or_extra_field_is_rejected(
    new_client: ClientFactory, tenant_a: SeedResult, change: object  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    before = copy.deepcopy(doc)
    change(doc)  # type: ignore[operator]
    response = save(admin, doc)
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Invalid field")
    assert draft_of(admin)["draft"] == before


def test_a_version_5_export_round_trips_and_a_version_4_export_gets_the_default_blocks(
    new_client: ClientFactory, tenant_a: SeedResult  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    exported = designed(draft_of(admin)["draft"])
    assert ok(admin.post(IMPORT_URL, json=exported))["theme"] == exported

    old = copy.deepcopy(exported)
    old["schema_version"] = 4
    del old["cards"]["blocks"]
    del old["layout"]["header_blocks"]
    del old["layout"]["categories"]
    imported = ok(admin.post(IMPORT_URL, json=old))["theme"]
    assert imported["schema_version"] == 5
    assert imported["cards"]["blocks"] == ["image", "heading", "description", "badges", "add_button"]
    assert imported["layout"]["header_blocks"] == ["banner", "name", "tagline", "welcome"]
    assert imported["layout"]["categories"] == {}
    assert imported["cards"]["template"] == exported["cards"]["template"]


def test_tables_cannot_change_the_blocks_and_tenants_never_see_each_other(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult  # noqa: F811
) -> None:
    owner_a = admin_of(new_client)
    owner_b = admin_of(new_client, "boss@example.com")
    tablet_a = tablet_of(new_client, created(create_table(owner_a)))
    tablet_b = tablet_of(new_client, created(create_table(owner_b)))
    doc = designed(draft_of(owner_a)["draft"])
    assert save(tablet_a, doc).status_code == 403
    assert draft_of(owner_a)["draft"]["layout"]["categories"] == {}

    ok(save(owner_a, doc))
    ok(owner_a.post(PUBLISH_URL))
    assert ok(tablet_a.get(THEME_URL))["theme"]["layout"]["categories"] == doc["layout"]["categories"]
    assert draft_of(owner_b)["draft"]["layout"]["categories"] == {}
    assert ok(tablet_b.get(THEME_URL))["theme"]["cards"]["blocks"] == ["image", "heading", "description", "badges", "add_button"]
