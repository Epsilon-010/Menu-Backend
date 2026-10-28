import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text

from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine
from tests.integration.modules.catalog.test_catalog_api import Json, ok
from tests.integration.modules.orders.test_ordering_api import ORDERS_URL, add, cart, menu_items, staff_of, submit
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tablet_of,
    tenant_a,
    tenant_b,
)

KITCHEN_URL = "/api/v1/kitchen/orders"
DELIVERIES_URL = "/api/v1/deliveries"
SETTINGS_URL = "/api/v1/orders/settings"


def status_url(order_id: str) -> str:
    return f"/api/v1/orders/{order_id}/items/status"


def mark(staff: TestClient, order: Json, items: list[Json], status: str, **extra: Any) -> Response:
    body = {"item_ids": [item["id"] for item in items], "status": status, **extra}
    return staff.post(status_url(order["id"]), json=body)


def send_order(tablet: TestClient, item_id: str, dishes: int) -> Json:
    """One order of `dishes` lines of the same menu item."""
    for n in range(dishes):
        ok(add(tablet, item_id, note=f"dish {n + 1}"))
    return ok(submit(tablet, cart(tablet)["version"]), 201)


def queue(staff: TestClient, url: str) -> list[Json]:
    body: list[Json] = ok(staff.get(url))  # type: ignore[assignment]
    return body


def statuses(order: Json) -> list[str]:
    return [item["status"] for item in order["items"]]


def keys(value: object) -> set[str]:
    """Every key anywhere in a JSON document."""
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in keys(child)}
    return set()


class Kitchen:
    """An admin, a tablet, a cook and a waiter of tenant A, with a menu item to order."""

    def __init__(self, new_client: ClientFactory) -> None:
        self.admin = admin_of(new_client)
        self.item = menu_items(self.admin)["pastor"]
        self.table = created(create_table(self.admin, "Mesa 1"))
        self.tablet = tablet_of(new_client, self.table)
        self.cook = staff_of(new_client, self.admin, "cook.day", "kitchen")
        self.waiter = staff_of(new_client, self.admin, "waiter.day", "waiter")

    def order(self, dishes: int = 1) -> Json:
        return send_order(self.tablet, self.item, dishes)


@pytest.fixture
def kitchen(new_client: ClientFactory, tenant_a: SeedResult) -> Kitchen:
    return Kitchen(new_client)


# --- Done when (S9) --------------------------------------------------------------------------------


def test_the_kitchen_releases_dishes_partially_and_the_waiter_delivers_them(kitchen: Kitchen) -> None:
    first, second, third = kitchen.order(), kitchen.order(4), kitchen.order()
    assert [order["number"] for order in queue(kitchen.cook, KITCHEN_URL)] == [1, 2, 3]
    assert queue(kitchen.waiter, DELIVERIES_URL) == []

    # The kitchen gets ahead with order 2 and releases 2 of its 4 dishes.
    ok(mark(kitchen.cook, second, second["items"], "preparing"))
    released = ok(mark(kitchen.cook, second, second["items"][:2], "ready"))
    assert statuses(released) == ["ready", "ready", "preparing", "preparing"]
    assert released["status"] == "in_progress"

    [card] = queue(kitchen.waiter, DELIVERIES_URL)
    assert (card["id"], card["number"], card["table_name"]) == (second["id"], 2, "Mesa 1")
    assert statuses(card) == ["ready", "ready", "preparing", "preparing"]
    assert all(item["ready_at"] for item in card["items"][:2])

    delivered = ok(mark(kitchen.waiter, second, second["items"][:2], "delivered"))
    assert delivered["status"] == "partially_delivered"
    assert queue(kitchen.waiter, DELIVERIES_URL) == []
    assert [order["number"] for order in queue(kitchen.cook, KITCHEN_URL)] == [1, 2, 3]

    ok(mark(kitchen.cook, second, second["items"][2:], "ready"))
    completed = ok(mark(kitchen.waiter, second, second["items"][2:], "delivered"))
    assert completed["status"] == "completed"
    assert [order["number"] for order in queue(kitchen.cook, KITCHEN_URL)] == [1, 3]
    assert queue(kitchen.waiter, DELIVERIES_URL) == []
    # The table sees each dish's status.
    by_id = {order["id"]: order for order in ok(kitchen.tablet.get(ORDERS_URL))}
    assert by_id[second["id"]]["status"] == "completed"
    assert by_id[first["id"]]["status"] == by_id[third["id"]]["status"] == "queued"


def test_deliveries_go_by_the_dish_ready_longest(kitchen: Kitchen) -> None:
    first, second = kitchen.order(), kitchen.order(2)
    ok(mark(kitchen.cook, second, second["items"][:1], "ready"))
    ok(mark(kitchen.cook, first, first["items"], "ready"))
    ok(mark(kitchen.cook, second, second["items"][1:], "ready"))

    assert [order["number"] for order in queue(kitchen.admin, DELIVERIES_URL)] == [2, 1]


# --- State machine, atomicity and races (S3, S4, S10) ----------------------------------------------


def test_an_invalid_transition_is_rejected_and_changes_nothing(kitchen: Kitchen) -> None:
    order = kitchen.order()

    refused = mark(kitchen.waiter, order, order["items"], "delivered")

    assert refused.status_code == 409
    assert refused.headers["content-type"] == "application/problem+json"
    assert refused.json()["detail"] == "Some dishes already changed; reload the order"
    assert statuses(queue(kitchen.cook, KITCHEN_URL)[0]) == ["queued"]


def test_one_dish_in_a_wrong_state_leaves_the_whole_batch_unchanged(kitchen: Kitchen) -> None:
    order = kitchen.order(3)
    ok(mark(kitchen.cook, order, order["items"][:1], "ready"))

    refused = mark(kitchen.cook, order, order["items"], "preparing")

    assert refused.status_code == 409
    assert statuses(queue(kitchen.cook, KITCHEN_URL)[0]) == ["ready", "queued", "queued"]
    assert history(kitchen) == [("queued", "ready", "cook.day", None)]


def test_two_cooks_marking_the_same_dish_at_once_make_one_transition(
    kitchen: Kitchen, new_client: ClientFactory
) -> None:
    order = kitchen.order()
    cooks = [kitchen.cook, staff_of(new_client, kitchen.admin, "cook.night", "kitchen")] + [
        staff_of(new_client, kitchen.admin, f"cook.extra{n}", "kitchen") for n in range(2)
    ]

    with ThreadPoolExecutor(len(cooks)) as pool:
        results = list(pool.map(lambda cook: mark(cook, order, order["items"], "preparing"), cooks))

    assert sorted(result.status_code for result in results) == [200, 409, 409, 409]
    assert len(history(kitchen)) == 1


def test_dishes_of_different_orders_cannot_be_marked_together(kitchen: Kitchen) -> None:
    order, other = kitchen.order(), kitchen.order()

    refused = mark(kitchen.cook, order, order["items"] + other["items"], "ready")

    assert refused.status_code == 422
    assert refused.json()["detail"] == "All dishes must belong to this order"
    assert [statuses(card) for card in queue(kitchen.cook, KITCHEN_URL)] == [["queued"], ["queued"]]


@pytest.mark.parametrize(
    "who, status, start",
    [("waiter", "preparing", None), ("waiter", "ready", None), ("cook", "delivered", "ready")],
)
def test_each_role_marks_only_what_it_may(kitchen: Kitchen, who: str, status: str, start: str | None) -> None:
    order = kitchen.order()
    if start:
        ok(mark(kitchen.cook, order, order["items"], start))

    refused = mark(getattr(kitchen, who), order, order["items"], status)

    assert refused.status_code == 403
    assert refused.json()["detail"] == f"Your role cannot mark dishes as {status}"


def test_the_checks_go_not_found_then_foreign_dishes_then_role_then_state(
    kitchen: Kitchen, new_client: ClientFactory
) -> None:
    order, other = kitchen.order(), kitchen.order()
    missing = {"id": str(uuid.uuid4())}

    assert mark(kitchen.waiter, missing, order["items"], "preparing").status_code == 404
    assert mark(kitchen.waiter, missing, order["items"], "preparing").json()["detail"] == "Order not found"
    assert mark(kitchen.waiter, order, other["items"], "preparing").status_code == 422
    assert mark(kitchen.waiter, order, order["items"], "preparing").status_code == 403
    assert mark(kitchen.cook, order, order["items"], "delivered").status_code == 403
    assert mark(kitchen.admin, order, order["items"], "delivered").status_code == 409


def test_cancelling_a_dish_needs_a_reason_the_table_and_waiters_see(kitchen: Kitchen) -> None:
    order = kitchen.order(2)

    assert mark(kitchen.cook, order, order["items"][:1], "cancelled").status_code == 422
    assert mark(kitchen.cook, order, order["items"][:1], "ready", reason="why").status_code == 422
    rejected = ok(mark(kitchen.cook, order, order["items"][:1], "cancelled", reason="Out of tortillas"))

    assert [item["cancel_reason"] for item in rejected["items"]] == ["Out of tortillas", None]
    [seen_by_table] = ok(kitchen.tablet.get(ORDERS_URL))
    assert [item["cancel_reason"] for item in seen_by_table["items"]] == ["Out of tortillas", None]
    assert seen_by_table["total_cents"] == 2500  # a cancelled dish is never charged
    # Only a dish nobody started can be cancelled.
    ok(mark(kitchen.cook, order, order["items"][1:], "preparing"))
    assert mark(kitchen.waiter, order, order["items"][1:], "cancelled", reason="Left").status_code == 409
    assert history(kitchen)[0] == ("queued", "cancelled", "cook.day", "Out of tortillas")


@pytest.mark.parametrize(
    "body",
    [
        {"item_ids": [], "status": "ready"},
        {"item_ids": [str(uuid.uuid4())] * 2, "status": "ready"},
        {"item_ids": [str(uuid.uuid4()) for _ in range(51)], "status": "ready"},
        {"item_ids": [str(uuid.uuid4())], "status": "queued"},
        {"item_ids": [str(uuid.uuid4())], "status": "cancelled", "reason": "x" * 201},
        {"item_ids": [str(uuid.uuid4())], "status": "ready", "extra": 1},
    ],
)
def test_a_malformed_status_change_is_422(kitchen: Kitchen, body: Json) -> None:
    order = kitchen.order()

    assert kitchen.cook.post(status_url(order["id"]), json=body).status_code == 422


def test_every_change_is_recorded_with_who_and_when(kitchen: Kitchen) -> None:
    order = kitchen.order()
    ok(mark(kitchen.cook, order, order["items"], "preparing"))
    ok(mark(kitchen.cook, order, order["items"], "ready"))
    ok(mark(kitchen.waiter, order, order["items"], "delivered"))

    assert history(kitchen) == [
        ("queued", "preparing", "cook.day", None),
        ("preparing", "ready", "cook.day", None),
        ("ready", "delivered", "waiter.day", None),
    ]
    [item] = ok(kitchen.tablet.get(ORDERS_URL))[0]["items"]
    assert item["status"] == "delivered"


def history(kitchen: Kitchen) -> list[tuple[str, str, str, str | None]]:
    """(from, to, username, reason) of every recorded change of tenant A, oldest first."""

    async def read() -> list[tuple[str, str, str, str | None]]:
        engine = create_engine(get_settings().database_url)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT c.from_status, c.to_status, u.username, c.reason, c.changed_at "
                        "FROM order_item_changes c JOIN users u ON u.id = c.changed_by "
                        "WHERE c.tenant_id = u.tenant_id ORDER BY c.changed_at, c.id"
                    )
                )
            ).all()
            result = [(row[0], row[1], row[2], row[3]) for row in rows]
            assert all(row[4] is not None for row in rows)
        await engine.dispose()
        return result

    return asyncio.run(read())


# --- Who sees what (S10, S11) ----------------------------------------------------------------------


def test_the_kitchen_never_sees_prices(kitchen: Kitchen) -> None:
    order = kitchen.order(2)
    changed = ok(mark(kitchen.cook, order, order["items"][:1], "ready"))
    documents = [queue(kitchen.cook, KITCHEN_URL), queue(kitchen.waiter, DELIVERIES_URL), changed]

    for document in documents:
        assert not {key for key in keys(document) if "cents" in key or "price" in key or "total" in key}
    assert set(changed) == {"id", "number", "table_id", "table_name", "sent_by", "created_at", "status", "items"}
    assert set(changed["items"][0]) == {
        "id", "name", "quantity", "note", "added_by", "status", "cancel_reason", "ready_at", "updated_at",
    }


def test_staff_of_another_tenant_cannot_see_or_change_the_orders(
    kitchen: Kitchen, new_client: ClientFactory, tenant_b: SeedResult
) -> None:
    order = kitchen.order()
    ok(mark(kitchen.cook, order, order["items"], "ready"))
    other_admin = admin_of(new_client, "boss@example.com")
    other_waiter = staff_of(new_client, other_admin, "waiter.burger", "waiter")
    other_cook = staff_of(new_client, other_admin, "cook.burger", "kitchen")

    assert queue(other_waiter, DELIVERIES_URL) == []
    assert queue(other_cook, KITCHEN_URL) == []
    refused = mark(other_waiter, order, order["items"], "delivered")
    assert (refused.status_code, refused.json()["detail"]) == (404, "Order not found")
    assert statuses(queue(kitchen.waiter, DELIVERIES_URL)[0]) == ["ready"]


def test_a_table_gets_403_on_every_staff_endpoint(kitchen: Kitchen) -> None:
    order = kitchen.order()

    assert kitchen.tablet.get(KITCHEN_URL).status_code == 403
    assert kitchen.tablet.get(DELIVERIES_URL).status_code == 403
    assert mark(kitchen.tablet, order, order["items"], "ready").status_code == 403
    assert kitchen.tablet.get(SETTINGS_URL).status_code == 403
    assert kitchen.tablet.patch(SETTINGS_URL, json={"late_order_minutes": 5}).status_code == 403
    assert kitchen.tablet.get("/api/v1/staff/events").status_code == 403


def test_the_queues_are_for_their_own_roles(kitchen: Kitchen) -> None:
    assert kitchen.waiter.get(KITCHEN_URL).status_code == 403
    assert kitchen.cook.get(DELIVERIES_URL).status_code == 403
    assert kitchen.admin.get(KITCHEN_URL).status_code == 200
    assert kitchen.admin.get(DELIVERIES_URL).status_code == 200


# --- Late order threshold (S6) ---------------------------------------------------------------------


def test_the_admin_sets_the_late_order_threshold_and_all_staff_read_it(kitchen: Kitchen) -> None:
    for staff in (kitchen.admin, kitchen.waiter, kitchen.cook):
        assert ok(staff.get(SETTINGS_URL)) == {"late_order_minutes": 15}

    assert ok(kitchen.admin.patch(SETTINGS_URL, json={"late_order_minutes": 25})) == {"late_order_minutes": 25}

    assert ok(kitchen.cook.get(SETTINGS_URL)) == {"late_order_minutes": 25}
    assert kitchen.waiter.patch(SETTINGS_URL, json={"late_order_minutes": 5}).status_code == 403
    assert kitchen.cook.patch(SETTINGS_URL, json={"late_order_minutes": 5}).status_code == 403


@pytest.mark.parametrize("value", [0, 241, "20", None, 1.5])
def test_the_late_order_threshold_must_be_1_to_240_minutes(kitchen: Kitchen, value: object) -> None:
    refused = kitchen.admin.patch(SETTINGS_URL, json={"late_order_minutes": value})

    assert refused.status_code == 422
    assert ok(kitchen.admin.get(SETTINGS_URL)) == {"late_order_minutes": 15}


def test_each_tenant_has_its_own_threshold(
    kitchen: Kitchen, new_client: ClientFactory, tenant_b: SeedResult
) -> None:
    ok(kitchen.admin.patch(SETTINGS_URL, json={"late_order_minutes": 40}))

    assert ok(admin_of(new_client, "boss@example.com").get(SETTINGS_URL)) == {"late_order_minutes": 15}
