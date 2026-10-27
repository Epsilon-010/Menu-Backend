import asyncio
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, update

from app.modules.media.infrastructure.jobs import CeleryImageCleanupScheduler
from app.modules.media.infrastructure.models import ImageUploadModel
from app.seed import SeedResult
from app.shared.domain.images import MAX_IMAGE_BYTES
from app.shared.infrastructure.celery_app import create_celery
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from app.shared.infrastructure.images import UnconfiguredImageStorage
from app.worker import clean_up_images_now
from tests.integration.modules.auth.test_auth_api import _seed, login
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, create_member, member_id
from tests.integration.modules.tables.test_tables_api import create_table, created, tablet_of
from tests.unit.fakes import FakeImageStorage

CATALOG_URL = "/api/v1/catalog"
CATEGORIES_URL = f"{CATALOG_URL}/categories"
ITEMS_URL = f"{CATALOG_URL}/items"
SIGNATURE_URL = f"{CATALOG_URL}/images/signature"

ClientFactory = Callable[[], TestClient]
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
    """Each actor has its own cookie jar; every app shares the fake image storage (never Cloudinary)."""
    from app.main import create_app

    with ExitStack() as stack:

        def factory() -> TestClient:
            app = create_app()
            app.state.image_storage = images
            return stack.enter_context(TestClient(app, base_url="https://testserver"))

        yield factory


def admin_of(new_client: ClientFactory, email: str = "owner@example.com") -> TestClient:
    client = new_client()
    assert login(client, username=email).status_code == 200
    return client


def ok(response: Response, status_code: int = 200) -> Json:
    assert response.status_code == status_code, response.text
    body: Json = response.json()
    return body


def create_category(admin: TestClient, name: str = "Tacos") -> Response:
    return admin.post(CATEGORIES_URL, json={"name": name})


def create_item(admin: TestClient, category_id: str, name: str = "Pastor", price_cents: Any = 2500) -> Response:
    return admin.post(
        ITEMS_URL, json={"category_id": category_id, "name": name, "description": "Con piña", "price_cents": price_cents}
    )


def upload_image(admin: TestClient, images: FakeImageStorage, image_format: str = "jpg", size: int = 1_000) -> str:
    """Plays the browser: asks for a signature, then uploads straight to the storage."""
    signature = ok(admin.post(SIGNATURE_URL))
    images.upload(signature["public_id"], image_format, size)
    return str(signature["public_id"])


def catalog(admin: TestClient) -> list[Json]:
    body: list[Json] = ok(admin.get(CATEGORIES_URL))  # type: ignore[assignment]
    return body


# --- Done when: "el admin crea, edita, reordena y oculta categorías e items con imagen desde el panel"


def test_admin_builds_the_catalog_with_images(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    tacos = ok(create_category(admin, " Tacos "), 201)
    drinks = ok(create_category(admin, "Bebidas"), 201)
    assert tacos == {"id": tacos["id"], "name": "Tacos", "position": 0, "is_visible": True}

    pastor = ok(create_item(admin, tacos["id"]), 201)
    assert pastor == {
        "id": pastor["id"],
        "category_id": tacos["id"],
        "name": "Pastor",
        "description": "Con piña",
        "price_cents": 2500,
        "position": 0,
        "is_available": True,
        "image": None,
    }
    suadero = ok(create_item(admin, tacos["id"], "Suadero", 2200), 201)

    signature = ok(admin.post(SIGNATURE_URL))
    assert signature["public_id"].startswith(f"tenants/{tenant_a.tenant_id}/items/")
    assert signature["allowed_formats"] == ["jpg", "png", "webp"]
    assert signature["max_bytes"] == MAX_IMAGE_BYTES
    assert signature["overwrite"] is False
    assert set(signature) == {
        "upload_url", "api_key", "timestamp", "signature", "public_id", "allowed_formats", "overwrite", "max_bytes"
    }
    images.upload(signature["public_id"])
    with_image = ok(admin.put(f"{ITEMS_URL}/{pastor['id']}/image", json={"public_id": signature["public_id"]}))
    assert with_image["image"] == {
        "public_id": signature["public_id"],
        "thumbnail_url": f"https://images.test/thumbnail/{signature['public_id']}",
        "card_url": f"https://images.test/card/{signature['public_id']}",
    }

    edited = ok(admin.patch(f"{ITEMS_URL}/{suadero['id']}", json={"price_cents": 2400, "is_available": False}))
    assert (edited["price_cents"], edited["is_available"]) == (2400, False)
    assert ok(admin.patch(f"{CATEGORIES_URL}/{drinks['id']}", json={"is_visible": False}))["is_visible"] is False
    assert admin.put(f"{CATEGORIES_URL}/order", json={"ids": [drinks["id"], tacos["id"]]}).status_code == 204
    assert admin.put(f"{CATEGORIES_URL}/{tacos['id']}/items/order", json={"ids": [suadero["id"], pastor["id"]]}).status_code == 204

    listed = catalog(admin)
    assert [(c["name"], c["position"], c["is_visible"]) for c in listed] == [("Bebidas", 0, False), ("Tacos", 1, True)]
    assert [(i["name"], i["is_available"], i["image"] is not None) for i in listed[1]["items"]] == [
        ("Suadero", False, False),
        ("Pastor", True, True),
    ]


def test_moving_an_item_puts_it_last_in_the_new_category(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    tacos = ok(create_category(admin), 201)
    specials = ok(create_category(admin, "Especiales"), 201)
    ok(create_item(admin, specials["id"], "Campechano"), 201)
    item = ok(create_item(admin, tacos["id"]), 201)

    moved = ok(admin.patch(f"{ITEMS_URL}/{item['id']}", json={"category_id": specials["id"], "name": "Pastor XL"}))

    assert (moved["category_id"], moved["position"], moved["name"]) == (specials["id"], 1, "Pastor XL")
    assert [len(c["items"]) for c in catalog(admin)] == [0, 2]


def test_catalog_input_is_validated(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    tacos = ok(create_category(admin), 201)
    item = ok(create_item(admin, tacos["id"]), 201)

    assert create_category(admin, "TACOS").status_code == 409
    assert create_category(admin, "  ").status_code == 422
    assert create_category(admin, "x" * 61).status_code == 422
    assert create_item(admin, tacos["id"], "x" * 81).status_code == 422
    # Prices are whole cents: no floats, no numeric strings, no negatives.
    for price in (12.5, 12.0, "1250", -1, 10_000_001, True):
        assert create_item(admin, tacos["id"], price_cents=price).status_code == 422, price
    assert admin.post(ITEMS_URL, json={"category_id": tacos["id"], "name": "X", "price_cents": 1, "tenant_id": "x"}).status_code == 422
    # A reorder lists every element exactly once.
    assert admin.put(f"{CATEGORIES_URL}/order", json={"ids": []}).status_code == 422
    assert admin.put(f"{CATEGORIES_URL}/{tacos['id']}/items/order", json={"ids": [item["id"], item["id"]]}).status_code == 422

    problem = create_category(admin, "TACOS")
    assert problem.headers["content-type"] == "application/problem+json"
    assert problem.json()["detail"] == "Category name already in use"


def test_only_empty_categories_can_be_deleted(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    tacos = ok(create_category(admin), 201)
    drinks = ok(create_category(admin, "Bebidas"), 201)
    item = ok(create_item(admin, tacos["id"]), 201)

    refused = admin.delete(f"{CATEGORIES_URL}/{tacos['id']}")
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Category still has items"
    assert admin.delete(f"{CATEGORIES_URL}/{drinks['id']}").status_code == 204
    assert admin.delete(f"{ITEMS_URL}/{item['id']}").status_code == 204
    assert admin.delete(f"{CATEGORIES_URL}/{tacos['id']}").status_code == 204

    assert catalog(admin) == []
    assert admin.delete(f"{ITEMS_URL}/{item['id']}").status_code == 404


# --- Images ------------------------------------------------------------------------------------


async def _age_upload(public_id: str, age: timedelta) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            await session.execute(
                update(ImageUploadModel)
                .where(ImageUploadModel.public_id == public_id)
                .values(created_at=func.now() - age)
            )
            await session.commit()
    finally:
        await engine.dispose()


def clean_up(images: FakeImageStorage) -> int:
    """Runs the worker's cleanup in-process against the test database and the fake storage."""
    return asyncio.run(clean_up_images_now(images))


def test_replacing_removing_or_deleting_discards_the_image_and_the_worker_deletes_it(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    item = ok(create_item(admin, ok(create_category(admin), 201)["id"]), 201)
    first, second, third = (upload_image(admin, images) for _ in range(3))

    ok(admin.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": first}))
    ok(admin.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": second}))
    assert ok(admin.delete(f"{ITEMS_URL}/{item['id']}/image"))["image"] is None
    ok(admin.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": third}))
    assert admin.delete(f"{ITEMS_URL}/{item['id']}").status_code == 204
    # Requests never delete from the storage themselves.
    assert images.deleted == []

    assert clean_up(images) == 3
    assert sorted(images.deleted) == sorted([first, second, third])
    assert clean_up(images) == 0


@pytest.mark.parametrize(("image_format", "size"), [("gif", 1_000), ("svg", 1_000), ("png", MAX_IMAGE_BYTES + 1)])
def test_uploads_with_a_wrong_format_or_size_are_rejected_and_cleaned_up(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage, image_format: str, size: int
) -> None:
    admin = admin_of(new_client)
    item = ok(create_item(admin, ok(create_category(admin), 201)["id"]), 201)
    public_id = upload_image(admin, images, image_format, size)

    response = admin.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": public_id})

    assert response.status_code == 422
    assert catalog(admin)[0]["items"][0]["image"] is None
    assert clean_up(images) == 1
    assert images.deleted == [public_id]


def test_an_upload_never_attached_is_cleaned_up_after_the_ttl(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    abandoned = upload_image(admin, images)
    fresh = upload_image(admin, images)
    # The browser uploaded `abandoned` two hours ago and the attach never arrived.
    asyncio.run(_age_upload(abandoned, timedelta(hours=2)))

    assert clean_up(images) == 1
    assert images.deleted == [abandoned]
    assert fresh in images.stored


def test_only_ids_signed_by_the_backend_can_be_attached(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    item = ok(create_item(admin, ok(create_category(admin), 201)["id"]), 201)
    # A file in the tenant folder that this backend never signed (e.g. uploaded with a leaked key).
    unsigned = f"tenants/{tenant_a.tenant_id}/items/{uuid.uuid4().hex}"
    images.upload(unsigned)

    response = admin.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": unsigned})

    assert response.status_code == 422
    assert catalog(admin)[0]["items"][0]["image"] is None


def test_a_broker_outage_never_fails_the_request(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    unreachable = get_settings().model_copy(update={"celery_broker_url": "amqp://guest:guest@127.0.0.1:1//"})
    admin.app.state.image_cleanup = CeleryImageCleanupScheduler(create_celery(unreachable))  # type: ignore[attr-defined]
    item = ok(create_item(admin, ok(create_category(admin), 201)["id"]), 201)
    public_id = upload_image(admin, images)
    ok(admin.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": public_id}))

    started = time.monotonic()
    response = admin.delete(f"{ITEMS_URL}/{item['id']}/image")

    assert response.status_code == 200
    assert time.monotonic() - started < 5
    # The periodic run still cleans it up: the work is recorded in Postgres, not in the broker.
    assert clean_up(images) == 1

def test_without_storage_credentials_signing_answers_503(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    admin.app.state.image_storage = UnconfiguredImageStorage()  # type: ignore[attr-defined]
    item = ok(create_item(admin, ok(create_category(admin), 201)["id"]), 201)

    response = admin.post(SIGNATURE_URL)

    assert response.status_code == 503
    assert response.json()["detail"] == "Image uploads are not configured"
    assert admin.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": "tenants/x/items/y"}).status_code == 422
    # The rest of the catalog keeps working.
    assert catalog(admin)[0]["items"][0]["name"] == "Pastor"


# --- Roles -------------------------------------------------------------------------------------


def _every_catalog_call(client: TestClient, category_id: str, item_id: str) -> list[Response]:
    return [
        client.get(CATEGORIES_URL),
        create_category(client, "Intrusa"),
        client.patch(f"{CATEGORIES_URL}/{category_id}", json={"is_visible": False}),
        client.delete(f"{CATEGORIES_URL}/{category_id}"),
        client.put(f"{CATEGORIES_URL}/order", json={"ids": [category_id]}),
        create_item(client, category_id, "Intruso"),
        client.patch(f"{ITEMS_URL}/{item_id}", json={"price_cents": 1}),
        client.delete(f"{ITEMS_URL}/{item_id}"),
        client.put(f"{CATEGORIES_URL}/{category_id}/items/order", json={"ids": [item_id]}),
        client.post(SIGNATURE_URL),
        client.put(f"{ITEMS_URL}/{item_id}/image", json={"public_id": "tenants/x/items/y"}),
        client.delete(f"{ITEMS_URL}/{item_id}/image"),
    ]


def test_tables_waiters_and_cooks_get_403_and_anonymous_401(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    category = ok(create_category(admin), 201)
    item = ok(create_item(admin, category["id"]), 201)
    tablet = tablet_of(new_client, created(create_table(admin)))
    staff = []
    for username, role in (("juan.mesero", "waiter"), ("ana.cocina", "kitchen")):
        member_id(create_member(admin, username, role))
        client = new_client()
        assert login(client, username=username, password=STAFF_PASSWORD).status_code == 200
        staff.append(client)

    for client in (tablet, *staff):
        assert [r.status_code for r in _every_catalog_call(client, category["id"], item["id"])] == [403] * 12
    assert [r.status_code for r in _every_catalog_call(new_client(), category["id"], item["id"])] == [401] * 12

    assert [(c["name"], c["is_visible"], len(c["items"])) for c in catalog(admin)] == [("Tacos", True, 1)]


# --- Done when: "los datos de otro tenant nunca aparecen (con test)" ---------------------------


def test_a_tenant_never_sees_nor_changes_another_tenant_catalog(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult, images: FakeImageStorage
) -> None:
    owner = admin_of(new_client)
    category = ok(create_category(owner), 201)
    item = ok(create_item(owner, category["id"]), 201)
    owner_image = upload_image(owner, images)
    other = admin_of(new_client, "boss@example.com")
    other_category = ok(create_category(other, "Burgers"), 201)
    other_item = ok(create_item(other, other_category["id"], "Clásica"), 201)
    other_image = upload_image(other, images)

    assert [c["name"] for c in catalog(other)] == ["Burgers"]
    responses = [
        other.patch(f"{CATEGORIES_URL}/{category['id']}", json={"is_visible": False}),
        other.delete(f"{CATEGORIES_URL}/{category['id']}"),
        other.put(f"{CATEGORIES_URL}/{category['id']}/items/order", json={"ids": [item["id"]]}),
        create_item(other, category["id"], "Intruso"),
        other.patch(f"{ITEMS_URL}/{item['id']}", json={"price_cents": 1}),
        other.patch(f"{ITEMS_URL}/{other_item['id']}", json={"category_id": category["id"]}),
        other.delete(f"{ITEMS_URL}/{item['id']}"),
        other.put(f"{ITEMS_URL}/{item['id']}/image", json={"public_id": other_image}),
        other.delete(f"{ITEMS_URL}/{item['id']}/image"),
    ]
    assert [r.status_code for r in responses] == [404] * 9
    # Another tenant's image cannot be attached to one's own item.
    assert other.put(f"{ITEMS_URL}/{other_item['id']}/image", json={"public_id": owner_image}).status_code == 422
    # A reorder that mixes in another tenant's category is rejected.
    assert other.put(f"{CATEGORIES_URL}/order", json={"ids": [other_category["id"], category["id"]]}).status_code == 422

    listed = catalog(owner)
    assert [(c["name"], c["is_visible"]) for c in listed] == [("Tacos", True)]
    assert [(i["name"], i["price_cents"], i["image"]) for i in listed[0]["items"]] == [("Pastor", 2500, None)]
    assert owner_image in images.stored
