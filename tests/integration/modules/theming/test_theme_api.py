import asyncio
import copy
import uuid
from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.seed import SeedResult
from app.shared.infrastructure.images import UnconfiguredImageStorage
from tests.integration.modules.auth.test_auth_api import _seed, login
from tests.integration.modules.catalog.test_catalog_api import ClientFactory, admin_of, ok
from tests.integration.modules.orders.test_guest_qr_api import guest_of, open_table
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, create_member
from tests.integration.modules.tables.test_tables_api import create_table, created, tablet_of
from tests.unit.fakes import FakeImageStorage

THEME_URL = "/api/v1/theme"
DRAFT_URL = f"{THEME_URL}/draft"
PUBLISH_URL = f"{THEME_URL}/publish"
SIGNATURE_URL = f"{THEME_URL}/images/signature"

Json = dict[str, Any]


@pytest.fixture
def tenant_a() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


@pytest.fixture
def tenant_b() -> SeedResult:
    return asyncio.run(_seed("Burger Place", "boss@example.com"))


@pytest.fixture
def images() -> FakeImageStorage:
    return FakeImageStorage()


@pytest.fixture
def new_client(images: FakeImageStorage) -> Iterator[ClientFactory]:
    from app.main import create_app

    with ExitStack() as stack:

        def factory() -> TestClient:
            app = create_app()
            app.state.image_storage = images
            return stack.enter_context(TestClient(app, base_url="https://testserver"))

        yield factory


def upload(admin: TestClient, images: FakeImageStorage, kind: str, image_format: str = "png") -> str:
    """Plays the browser: asks for a signature for that slot, then uploads straight to the storage."""
    signature = ok(admin.post(SIGNATURE_URL, json={"kind": kind}))
    images.upload(signature["public_id"], image_format)
    return str(signature["public_id"])


def draft_of(admin: TestClient) -> Json:
    return ok(admin.get(DRAFT_URL))


def save(admin: TestClient, doc: Json) -> Any:
    return admin.put(DRAFT_URL, json=doc)


# --- Done when: "cambio colores y logo en el editor, los veo en la vista previa sin afectar las mesas, publico y
# la tablet muestra el nuevo diseño"


def test_admin_changes_colors_and_logo_in_the_draft_and_tables_see_it_only_after_publishing(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    tablet = tablet_of(new_client, created(create_table(admin)))

    state = draft_of(admin)
    defaults = state["draft"]
    assert state["published"] is None and state["published_at"] is None
    assert state["has_unpublished_changes"] is False
    assert state["contrast_warnings"] == []
    assert state["defaults"]["light"] == defaults["colors"]
    assert state["defaults"]["dark"]["mode"] == "dark"
    assert ok(tablet.get(THEME_URL)) == {"theme": defaults, "image_urls": {}}

    logo = upload(admin, images, "logo", "svg")
    doc = draft_of(admin)["draft"]
    doc["colors"]["primary"] = "#ABC"
    doc["brand"]["logo"]["image_id"] = logo
    doc["brand"]["name"] = "  Tacos El Primo  "
    saved = ok(save(admin, doc))
    assert saved["draft"]["colors"]["primary"] == "#aabbcc"
    assert saved["draft"]["brand"]["name"] == "Tacos El Primo"
    assert saved["image_urls"] == {logo: f"https://images.test/logo/{logo}"}
    assert saved["has_unpublished_changes"] is True

    # The table keeps the published (here: default) design, even after reading it once (cached).
    assert ok(tablet.get(THEME_URL))["theme"] == defaults

    published = ok(admin.post(PUBLISH_URL))
    assert published["published"] == published["draft"] == saved["draft"]
    assert published["published_at"] is not None
    assert published["has_unpublished_changes"] is False
    seen = ok(tablet.get(THEME_URL))
    assert seen == {"theme": saved["draft"], "image_urls": {logo: f"https://images.test/logo/{logo}"}}


# --- "un valor inválido (color mal formado, CSS inyectado) es rechazado (con test)"


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("colors", "primary", "blue"),
        ("colors", "primary", "#12345"),
        ("colors", "background", "#fff;}body{background:url(https://evil.test/x)}"),
        ("colors", "text", "</style><script>alert(1)</script>"),
        ("colors", "price", "url(javascript:alert(1))"),
    ],
)
def test_a_malformed_color_or_injected_css_is_rejected_and_nothing_changes(
    new_client: ClientFactory, tenant_a: SeedResult, section: str, field: str, value: str
) -> None:
    admin = admin_of(new_client)
    before = draft_of(admin)
    doc = copy.deepcopy(before["draft"])
    doc[section][field] = value
    response = save(admin, doc)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == f"Invalid theme value: {section}.{field}"
    assert value not in response.text
    assert draft_of(admin) == before


def test_unknown_fields_like_raw_css_are_rejected(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    doc["custom_css"] = "body { display: none }"
    response = save(admin, doc)
    assert response.status_code == 422
    assert "custom_css" in response.json()["detail"]

    doc = draft_of(admin)["draft"]
    doc["brand"]["banner"]["image_url"] = "https://evil.test/banner.png"
    assert save(admin, doc).status_code == 422


def test_low_contrast_is_a_warning_not_an_error(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    doc["colors"]["button_bg"] = "#ffffff"
    doc["colors"]["button_text"] = "#eeeeee"
    warnings = ok(save(admin, doc))["contrast_warnings"]
    assert [(w["foreground"], w["background"]) for w in warnings] == [("button_text", "button_bg")]
    assert warnings[0]["ratio"] < 4.5


def test_images_from_another_folder_or_unsigned_are_rejected(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    banner = upload(admin, images, "banner")
    doc = draft_of(admin)["draft"]
    doc["brand"]["logo"]["image_id"] = banner
    assert save(admin, doc).status_code == 422

    unsigned = f"tenants/{tenant_a.tenant_id}/logos/{uuid.uuid4().hex}"
    images.upload(unsigned, "png")
    doc["brand"]["logo"]["image_id"] = unsigned
    response = save(admin, doc)
    assert response.status_code == 422
    assert response.json()["detail"] == "Use an image uploaded for this slot; that one is not available"

    assert admin.post(SIGNATURE_URL, json={"kind": "items"}).status_code == 422
    assert admin.post(SIGNATURE_URL, json={"kind": "logo", "folder": "x"}).status_code == 422


def test_uploading_without_image_storage_is_503_but_colors_still_save(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    client = new_client()
    client.app.state.image_storage = UnconfiguredImageStorage()  # type: ignore[attr-defined]
    assert login(client, username="owner@example.com").status_code == 200
    response = client.post(SIGNATURE_URL, json={"kind": "logo"})
    assert response.status_code == 503
    doc = draft_of(client)["draft"]
    doc["colors"]["accent"] = "#00ff00"
    assert ok(save(client, doc))["draft"]["colors"]["accent"] == "#00ff00"


# --- Roles: only the admin edits; every signed-in role of the tenant reads the published theme


def test_only_the_admin_reads_the_draft_saves_publishes_or_signs_uploads(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    assert create_member(admin, "theme.waiter", "waiter").status_code == 201
    assert create_member(admin, "theme.cook", "kitchen").status_code == 201
    waiter, cook = new_client(), new_client()
    assert login(waiter, "theme.waiter", STAFF_PASSWORD).status_code == 200
    assert login(cook, "theme.cook", STAFF_PASSWORD).status_code == 200
    anonymous = new_client()
    doc = draft_of(admin)["draft"]
    doc["colors"]["primary"] = "#000000"

    for client in (tablet, guest, waiter, cook):
        assert client.get(DRAFT_URL).status_code == 403
        assert save(client, doc).status_code == 403
        assert client.post(PUBLISH_URL).status_code == 403
        assert client.post(SIGNATURE_URL, json={"kind": "logo"}).status_code == 403
        assert ok(client.get(THEME_URL))["theme"]["colors"]["primary"] != "#000000"
    for request in (
        lambda: anonymous.get(THEME_URL),
        lambda: anonymous.get(DRAFT_URL),
        lambda: save(anonymous, doc),
        lambda: anonymous.post(PUBLISH_URL),
    ):
        assert request().status_code == 401


def test_a_tenant_never_sees_nor_changes_another_tenant_theme(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult, images: FakeImageStorage
) -> None:
    owner_a = admin_of(new_client)
    owner_b = admin_of(new_client, "boss@example.com")
    tablet_b = tablet_of(new_client, created(create_table(owner_b)))
    defaults = draft_of(owner_b)["draft"]

    logo_a = upload(owner_a, images, "logo")
    doc = draft_of(owner_a)["draft"]
    doc["colors"]["primary"] = "#111111"
    doc["brand"]["logo"]["image_id"] = logo_a
    ok(save(owner_a, doc))
    ok(owner_a.post(PUBLISH_URL))

    assert draft_of(owner_b)["draft"] == defaults
    assert ok(tablet_b.get(THEME_URL))["theme"] == defaults

    # B cannot use A's uploaded logo, and publishing B does not change A.
    doc_b = draft_of(owner_b)["draft"]
    doc_b["brand"]["logo"]["image_id"] = logo_a
    assert save(owner_b, doc_b).status_code == 422
    ok(owner_b.post(PUBLISH_URL))
    assert ok(owner_a.get(THEME_URL))["theme"]["colors"]["primary"] == "#111111"
