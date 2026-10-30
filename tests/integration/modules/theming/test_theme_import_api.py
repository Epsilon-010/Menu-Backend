"""Slice 14: exporting a design from one business and importing it into another, older versions included."""

from typing import Any

import pytest

from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import login
from tests.integration.modules.catalog.test_catalog_api import ClientFactory, admin_of, ok
from tests.integration.modules.orders.test_guest_qr_api import guest_of, open_table
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, create_member
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
    upload,
)
from tests.unit.fakes import FakeImageStorage

IMPORT_URL = f"{THEME_URL}/import"


def test_a_design_exported_by_one_business_is_imported_by_another_without_its_images(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
    tenant_b: SeedResult,  # noqa: F811
    images: FakeImageStorage,  # noqa: F811
) -> None:
    owner_a = admin_of(new_client)
    owner_b = admin_of(new_client, "boss@example.com")
    tablet_b = tablet_of(new_client, created(create_table(owner_b)))
    logo_a = upload(owner_a, images, "logo")
    doc = draft_of(owner_a)["draft"]
    doc["colors"]["primary"] = "#123456"
    doc["layout"]["navigation"] = "tabs"
    doc["cards"]["template"] = "overlay"
    doc["brand"]["logo"]["image_id"] = logo_a
    exported = ok(save(owner_a, doc))["draft"]  # the editor downloads the draft as it is

    imported = ok(owner_b.post(IMPORT_URL, json=exported))
    assert imported["removed_images"] == ["logo"]
    assert imported["image_urls"] == {}
    assert imported["theme"] == {**exported, "brand": {**exported["brand"], "logo": {**exported["brand"]["logo"], "image_id": None}}}
    defaults = draft_of(owner_b)["draft"]
    assert defaults["colors"]["primary"] != "#123456"  # importing saves nothing

    ok(save(owner_b, imported["theme"]))
    ok(owner_b.post(PUBLISH_URL))
    seen = ok(tablet_b.get(THEME_URL))["theme"]
    assert (seen["colors"]["primary"], seen["layout"]["navigation"], seen["cards"]["template"]) == ("#123456", "tabs", "overlay")
    assert draft_of(owner_a)["draft"]["brand"]["logo"]["image_id"] == logo_a  # A keeps its own


def test_an_own_export_keeps_the_images_its_themes_still_use(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
    images: FakeImageStorage,  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    logo = upload(admin, images, "logo")
    doc = draft_of(admin)["draft"]
    doc["brand"]["logo"]["image_id"] = logo
    exported = ok(save(admin, doc))["draft"]

    imported = ok(admin.post(IMPORT_URL, json=exported))
    assert imported["removed_images"] == []
    assert imported["theme"] == exported
    assert imported["image_urls"] == {logo: f"https://images.test/logo/{logo}"}


def test_an_export_of_an_older_version_is_upgraded(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    current = draft_of(admin)["draft"]
    old = {key: value for key, value in current.items() if key not in ("layout", "cards")}
    old["schema_version"] = 2
    old["colors"] = {**current["colors"], "primary": "#654321"}

    imported = ok(admin.post(IMPORT_URL, json=old))["theme"]
    assert imported == {**current, "colors": old["colors"]}


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        (lambda doc: doc.update(schema_version=5), "Invalid theme value: schema_version"),
        (lambda doc: doc["colors"].update(primary="url(javascript:alert(1))"), "Invalid theme value: colors.primary"),
        (lambda doc: doc.update(css="body{}"), "Invalid theme value: css"),
        (lambda doc: doc.pop("brand"), "Invalid theme value: brand"),
    ],
)
def test_an_invalid_export_is_rejected_naming_the_field_never_the_value(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
    change: Any,
    detail: str,
) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    change(doc)
    response = admin.post(IMPORT_URL, json=doc)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == detail


@pytest.mark.parametrize("body", [[], "theme", 4, None])
def test_something_that_is_not_a_json_object_is_rejected(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
    body: Any,
) -> None:
    admin = admin_of(new_client)
    assert admin.post(IMPORT_URL, json=body).status_code == 422


def test_only_the_admin_imports(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    assert create_member(admin, "import.waiter", "waiter").status_code == 201
    assert create_member(admin, "import.cook", "kitchen").status_code == 201
    waiter, cook = new_client(), new_client()
    assert login(waiter, "import.waiter", STAFF_PASSWORD).status_code == 200
    assert login(cook, "import.cook", STAFF_PASSWORD).status_code == 200

    for client in (tablet, guest, waiter, cook):
        assert client.post(IMPORT_URL, json=doc).status_code == 403
    assert new_client().post(IMPORT_URL, json=doc).status_code == 401
