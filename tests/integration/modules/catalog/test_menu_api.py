import asyncio
import uuid

from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.modules.catalog.infrastructure.menu_cache import RedisMenuCache
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from tests.integration.modules.catalog.test_catalog_api import (
    CATEGORIES_URL,
    ITEMS_URL,
    ClientFactory,
    Json,
    admin_of,
    create_category,
    create_item,
    ok,
    tenant_a,  # noqa: F401  (fixture)
    tenant_b,  # noqa: F401  (fixture)
    images,  # noqa: F401  (fixture)
    new_client,  # noqa: F401  (fixture)
    upload_image,
)
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, create_member
from tests.integration.modules.auth.test_auth_api import login
from tests.integration.modules.tables.test_tables_api import create_table, created, tablet_of
from tests.unit.fakes import FakeImageStorage

MENU_URL = "/api/v1/menu"


def menu(client: TestClient) -> list[Json]:
    body: list[Json] = ok(client.get(MENU_URL))  # type: ignore[assignment]
    return body


def build_menu(admin: TestClient) -> dict[str, str]:
    """Tacos (visible: Pastor available, Suadero not), Postres (hidden), Bebidas (visible, empty)."""
    tacos = ok(create_category(admin, "Tacos"), 201)["id"]
    postres = ok(create_category(admin, "Postres"), 201)["id"]
    ok(create_category(admin, "Bebidas"), 201)
    pastor = ok(create_item(admin, tacos, "Pastor", 2500), 201)["id"]
    suadero = ok(create_item(admin, tacos, "Suadero", 2700), 201)["id"]
    ok(create_item(admin, postres, "Flan", 4000), 201)
    ok(admin.patch(f"{ITEMS_URL}/{suadero}", json={"is_available": False}))
    ok(admin.patch(f"{CATEGORIES_URL}/{postres}", json={"is_visible": False}))
    return {"tacos": tacos, "pastor": pastor, "suadero": suadero}


def test_the_table_sees_only_visible_categories_with_available_items(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage
) -> None:
    admin = admin_of(new_client)
    ids = build_menu(admin)
    public_id = upload_image(admin, images)
    ok(admin.put(f"{ITEMS_URL}/{ids['pastor']}/image", json={"public_id": public_id}))
    tablet = tablet_of(new_client, created(create_table(admin)))

    assert menu(tablet) == [
        {
            "id": ids["tacos"],
            "name": "Tacos",
            "items": [
                {
                    "id": ids["pastor"],
                    "name": "Pastor",
                    "description": "Con piña",
                    "price_cents": 2500,
                    "image": {
                        "thumbnail_url": f"https://images.test/thumbnail/{public_id}",
                        "card_url": f"https://images.test/card/{public_id}",
                    },
                }
            ],
        }
    ]


def test_every_role_reads_the_menu_and_anonymous_gets_401(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    build_menu(admin)
    create_member(admin, "cook", "kitchen")
    cook = new_client()
    assert login(cook, username="cook", password=STAFF_PASSWORD).status_code == 200

    assert [category["name"] for category in menu(admin)] == ["Tacos"]
    assert [category["name"] for category in menu(cook)] == ["Tacos"]
    assert new_client().get(MENU_URL).status_code == 401


def test_catalog_changes_reach_the_cached_menu_right_away(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    ids = build_menu(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    assert [item["name"] for item in menu(tablet)[0]["items"]] == ["Pastor"]  # now cached

    ok(admin.patch(f"{ITEMS_URL}/{ids['suadero']}", json={"is_available": True}))
    assert [item["name"] for item in menu(tablet)[0]["items"]] == ["Pastor", "Suadero"]

    ok(admin.patch(f"{ITEMS_URL}/{ids['pastor']}", json={"price_cents": 2600}))
    assert menu(tablet)[0]["items"][0]["price_cents"] == 2600

    ok(admin.patch(f"{CATEGORIES_URL}/{ids['tacos']}", json={"is_visible": False}))
    assert menu(tablet) == []


def test_a_menu_read_before_a_change_is_never_served_after_it() -> None:
    async def scenario() -> tuple[str | None, str | None]:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            cache = RedisMenuCache(redis)
            tenant_id = uuid.uuid4()
            generation, _ = await cache.get(tenant_id)  # a reader starts reading Postgres...
            await cache.invalidate(tenant_id)  # ...the admin changes the catalog meanwhile...
            assert generation is not None
            await cache.put(tenant_id, generation, "stale")  # ...and the reader stores what it read.
            return await cache.get(tenant_id)
        finally:
            await redis.aclose()

    assert asyncio.run(scenario()) == ("1", None)


def test_a_tenant_never_sees_another_tenant_menu(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    build_menu(admin_of(new_client))
    other = admin_of(new_client, "boss@example.com")
    other_tablet = tablet_of(new_client, created(create_table(other)))
    assert menu(other_tablet) == []
    ok(create_category(other, "Hamburguesas"), 201)
    assert [category["name"] for category in menu(admin_of(new_client))] == ["Tacos"]
