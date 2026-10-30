"""Slice 14: the history of published themes, restored through the draft."""

from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import ClientFactory, admin_of, ok
from tests.integration.modules.orders.test_guest_qr_api import guest_of, open_table
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, create_member
from tests.integration.modules.auth.test_auth_api import login
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

VERSIONS_URL = f"{THEME_URL}/versions"


def publish_primary(admin: TestClient, primary: str) -> Json:
    doc = draft_of(admin)["draft"]
    doc["colors"]["primary"] = primary
    ok(save(admin, doc))
    return ok(admin.post(PUBLISH_URL))


def test_admin_publishes_twice_and_restores_the_first_version_through_the_draft(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
    images: FakeImageStorage,  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    tablet = tablet_of(new_client, created(create_table(admin)))
    assert ok(admin.get(VERSIONS_URL)) == {"versions": [], "image_urls": {}}

    logo = upload(admin, images, "logo")
    doc = draft_of(admin)["draft"]
    doc["colors"]["primary"] = "#111111"
    doc["brand"]["logo"]["image_id"] = logo
    first = ok(save(admin, doc))["draft"]
    first_published_at = ok(admin.post(PUBLISH_URL))["published_at"]
    publish_primary(admin, "#222222")  # keeps the logo

    history = ok(admin.get(VERSIONS_URL))
    assert [version["number"] for version in history["versions"]] == [2, 1]
    assert history["versions"][1]["theme"] == first
    assert history["versions"][1]["published_at"] == first_published_at
    assert history["image_urls"] == {logo: f"https://images.test/logo/{logo}"}

    # Restoring is saving that version as the draft: the tables keep the published one until the admin publishes.
    restored = ok(save(admin, history["versions"][1]["theme"]))
    assert restored["has_unpublished_changes"] is True
    assert ok(tablet.get(THEME_URL))["theme"]["colors"]["primary"] == "#222222"
    ok(admin.post(PUBLISH_URL))
    assert ok(tablet.get(THEME_URL))["theme"] == first
    assert [version["number"] for version in ok(admin.get(VERSIONS_URL))["versions"]] == [3, 2, 1]


def test_only_the_last_20_versions_are_kept(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    for number in range(1, 23):
        publish_primary(admin, f"#0000{number:02x}")

    versions = ok(admin.get(VERSIONS_URL))["versions"]
    assert [version["number"] for version in versions] == list(range(22, 2, -1))
    assert versions[0]["theme"]["colors"]["primary"] == "#000016"


def test_only_the_admin_reads_the_history(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
) -> None:
    admin = admin_of(new_client)
    publish_primary(admin, "#111111")
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    assert create_member(admin, "history.waiter", "waiter").status_code == 201
    assert create_member(admin, "history.cook", "kitchen").status_code == 201
    waiter, cook = new_client(), new_client()
    assert login(waiter, "history.waiter", STAFF_PASSWORD).status_code == 200
    assert login(cook, "history.cook", STAFF_PASSWORD).status_code == 200

    for client in (tablet, guest, waiter, cook):
        assert client.get(VERSIONS_URL).status_code == 403
    assert new_client().get(VERSIONS_URL).status_code == 401


def test_a_tenant_never_sees_another_tenant_history(
    new_client: ClientFactory,  # noqa: F811
    tenant_a: SeedResult,  # noqa: F811
    tenant_b: SeedResult,  # noqa: F811
) -> None:
    owner_a = admin_of(new_client)
    owner_b = admin_of(new_client, "boss@example.com")
    publish_primary(owner_a, "#111111")
    publish_primary(owner_b, "#222222")

    seen_by_b = ok(owner_b.get(VERSIONS_URL))["versions"]
    assert [(v["number"], v["theme"]["colors"]["primary"]) for v in seen_by_b] == [(1, "#222222")]
    assert len(ok(owner_a.get(VERSIONS_URL))["versions"]) == 1
