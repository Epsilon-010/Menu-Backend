import asyncio
import copy
import uuid
from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
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


# --- Typography (Slice 11): "cada elemento del menú puede tener su propia fuente y tamaño, se ve en la vista previa y
# se aplica al publicar"


def test_each_element_gets_its_own_font_and_size_and_tables_see_it_only_after_publishing(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    tablet = tablet_of(new_client, created(create_table(admin)))
    doc = draft_of(admin)["draft"]
    assert doc["schema_version"] == 2
    doc["typography"]["fonts"]["heading"] = "playfair_display"
    doc["typography"]["fonts"]["price"] = "oswald"
    doc["typography"]["elements"]["business_name"].update(size=48, weight=800, style="italic", transform="uppercase")
    doc["typography"]["elements"]["price"].update(font="price", size=20, weight=700)
    saved = ok(save(admin, doc))["draft"]["typography"]
    assert saved == doc["typography"]

    assert ok(tablet.get(THEME_URL))["theme"]["typography"]["fonts"]["heading"] == "geist"
    ok(admin.post(PUBLISH_URL))
    published = ok(tablet.get(THEME_URL))["theme"]["typography"]
    assert published["fonts"]["heading"] == "playfair_display"
    assert published["elements"]["business_name"]["size"] == 48
    assert published["elements"]["price"]["weight"] == 700


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("fonts", "heading"), "comic_sans"),
        (("fonts", "body"), "Inter; } body { display: none"),
        (("fonts", "button"), "https://evil.test/font.woff2"),
        (("scale",), 200),
        (("elements", "category", "size"), 9),
        (("elements", "category", "line_height"), 500),
        (("elements", "category", "letter_spacing"), -100),
        (("elements", "category", "align"), "justify"),
        (("elements", "category", "transform"), "small-caps"),
        (("elements", "description", "style"), "italic"),  # Geist has no italics
        (("elements", "price", "weight"), 650),
    ],
)
def test_a_font_outside_the_list_or_a_value_out_of_range_is_rejected_and_nothing_changes(
    new_client: ClientFactory, tenant_a: SeedResult, path: tuple[str, ...], value: Any
) -> None:
    admin = admin_of(new_client)
    before = draft_of(admin)
    doc = copy.deepcopy(before["draft"])
    target = doc["typography"]
    *parents, leaf = path
    for key in parents:
        target = target[key]
    target[leaf] = value
    response = save(admin, doc)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == f"Invalid theme value: typography.{'.'.join(path)}"
    assert str(value) not in response.json()["detail"]
    assert draft_of(admin) == before


def test_a_weight_the_chosen_font_does_not_have_is_rejected(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    doc = draft_of(admin)["draft"]
    doc["typography"]["fonts"]["price"] = "bebas_neue"  # only 400; price defaults to 600
    response = save(admin, doc)
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid theme value: typography.elements.price.weight"
    doc["typography"]["elements"]["price"]["weight"] = 400
    assert ok(save(admin, doc))["draft"]["typography"]["fonts"]["price"] == "bebas_neue"


def test_tables_guests_and_staff_cannot_change_the_typography(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    doc = draft_of(admin)["draft"]
    doc["typography"]["fonts"]["heading"] = "pacifico"
    doc["typography"]["elements"]["business_name"]["weight"] = 400
    for client in (tablet, guest):
        assert save(client, doc).status_code == 403
        assert client.post(PUBLISH_URL).status_code == 403
    assert draft_of(admin)["draft"]["typography"]["fonts"]["heading"] == "geist"
    assert ok(tablet.get(THEME_URL))["theme"]["typography"]["fonts"]["heading"] == "geist"


def test_a_tenant_typography_never_reaches_another_tenant(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    owner_a = admin_of(new_client)
    owner_b = admin_of(new_client, "boss@example.com")
    tablet_b = tablet_of(new_client, created(create_table(owner_b)))
    doc = draft_of(owner_a)["draft"]
    doc["typography"]["fonts"]["heading"] = "lora"
    doc["typography"]["scale"] = 120
    ok(save(owner_a, doc))
    ok(owner_a.post(PUBLISH_URL))
    for typography in (draft_of(owner_b)["draft"]["typography"], ok(tablet_b.get(THEME_URL))["theme"]["typography"]):
        assert typography["fonts"]["heading"] == "geist"
        assert typography["scale"] == 100


def test_a_theme_cached_before_the_schema_change_is_never_served(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    stale = '{"theme": {"schema_version": 1}, "image_urls": {}}'
    with Redis.from_url(get_settings().redis_url) as redis:
        # Where Slice 10 stored the published theme of generation 0.
        redis.set(f"theme:{tenant_a.tenant_id}:0", stale)
    assert ok(admin.get(THEME_URL))["theme"]["schema_version"] == 2


# --- Presets (templates): "si no quiere personalizar el menú o quieren algo rápido las seleccione"


def test_admin_applies_a_preset_keeping_the_brand_and_tables_see_it_only_after_publishing(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    tablet = tablet_of(new_client, created(create_table(admin)))
    logo = upload(admin, images, "logo", "svg")
    doc = draft_of(admin)["draft"]
    doc["brand"]["name"] = "Tacos El Primo"
    doc["brand"]["logo"]["image_id"] = logo
    mine = ok(save(admin, doc))["draft"]
    ok(admin.post(PUBLISH_URL))

    presets = draft_of(admin)["presets"]
    assert [preset["id"] for preset in presets][:1] == ["classic"]
    assert presets[0]["colors"] == mine["colors"] and presets[0]["typography"] == mine["typography"]
    assert set(presets[0]) == {"id", "name", "description", "colors", "typography"}
    street = next(preset for preset in presets if preset["id"] == "street")

    # The editor applies it to the draft: colors and typography change, the brand stays.
    applied = {**mine, "colors": street["colors"], "typography": street["typography"]}
    saved = ok(save(admin, applied))
    assert saved["draft"] == applied
    assert saved["draft"]["brand"] == mine["brand"]
    assert saved["contrast_warnings"] == []
    assert ok(tablet.get(THEME_URL))["theme"] == mine

    ok(admin.post(PUBLISH_URL))
    assert ok(tablet.get(THEME_URL))["theme"] == applied


def test_presets_come_with_every_draft_response(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    expected = draft_of(admin)["presets"]
    assert len(expected) >= 6
    assert ok(save(admin, draft_of(admin)["draft"]))["presets"] == expected
    assert ok(admin.post(PUBLISH_URL))["presets"] == expected
