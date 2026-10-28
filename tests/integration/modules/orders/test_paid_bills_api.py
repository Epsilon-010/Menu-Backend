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
from tests.integration.modules.catalog.test_catalog_api import ITEMS_URL, Json, ok
from tests.integration.modules.orders.test_guest_qr_api import open_table, pay
from tests.integration.modules.orders.test_kitchen_api import (
    DELIVERIES_URL,
    KITCHEN_URL,
    mark,
    queue,
    send_order,
)
from tests.integration.modules.orders.test_ordering_api import BILLS_URL, menu_items, staff_of
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

PAID = "This bill is already paid; its dishes can no longer change"


def dishes_url(order_id: str) -> str:
    return f"/api/v1/orders/{order_id}/items"


def add_dish(staff: TestClient, order: Json, item_id: str, quantity: int = 1, **extra: Any) -> Response:
    return staff.post(dishes_url(order["id"]), json={"item_id": item_id, "quantity": quantity, **extra})


def bill_total(staff: TestClient, bill_id: str) -> int:
    return int(ok(staff.get(f"{BILLS_URL}/{bill_id}"))["total_cents"])


def paid_cents(bill_id: str) -> int | None:
    async def read() -> int | None:
        engine = create_engine(get_settings().database_url)
        async with engine.connect() as conn:
            value = await conn.scalar(text("SELECT paid_cents FROM bills WHERE id = :id"), {"id": bill_id})
        await engine.dispose()
        return value

    return asyncio.run(read())


def history_count() -> int:
    async def read() -> int:
        engine = create_engine(get_settings().database_url)
        async with engine.connect() as conn:
            value = await conn.scalar(text("SELECT count(*) FROM order_item_changes"))
        await engine.dispose()
        return int(value or 0)

    return asyncio.run(read())


class Visit:
    """Tenant A: an open table with one order of two Pastor (2500 each), a cook and a waiter."""

    def __init__(self, new_client: ClientFactory) -> None:
        self.admin = admin_of(new_client)
        self.items = menu_items(self.admin)
        self.table = created(create_table(self.admin, "Mesa 1"))
        self.tablet = tablet_of(new_client, self.table)
        self.cook = staff_of(new_client, self.admin, "cook.day", "kitchen")
        self.waiter = staff_of(new_client, self.admin, "waiter.day", "waiter")
        self.bill_id = open_table(self.waiter, self.table)
        self.order = send_order(self.tablet, self.items["pastor"], 2)


@pytest.fixture
def visit(new_client: ClientFactory, tenant_a: SeedResult) -> Visit:
    return Visit(new_client)


# --- A paid bill is frozen ------------------------------------------------------------------------


def test_cancelling_a_dish_after_payment_is_refused_and_the_paid_total_stays(visit: Visit) -> None:
    assert bill_total(visit.waiter, visit.bill_id) == 5000
    pay(visit.waiter, visit.bill_id)

    refused = mark(visit.cook, visit.order, visit.order["items"][:1], "cancelled", reason="Out of tortillas")

    assert refused.status_code == 409
    assert refused.json()["detail"] == PAID
    assert bill_total(visit.waiter, visit.bill_id) == 5000
    assert paid_cents(visit.bill_id) == 5000
    assert history_count() == 0


@pytest.mark.parametrize(
    "who, start, target",
    [
        ("cook", None, "preparing"),
        ("cook", None, "ready"),
        ("waiter", "ready", "delivered"),
        ("waiter", None, "cancelled"),
    ],
)
def test_no_dish_of_a_paid_bill_can_change(visit: Visit, who: str, start: str | None, target: str) -> None:
    if start:
        ok(mark(visit.cook, visit.order, visit.order["items"], start))
    pay(visit.waiter, visit.bill_id)
    before = history_count()
    extra = {"reason": "No longer wanted"} if target == "cancelled" else {}

    refused = mark(getattr(visit, who), visit.order, visit.order["items"], target, **extra)

    assert (refused.status_code, refused.json()["detail"]) == (409, PAID)
    assert history_count() == before


def test_the_role_and_foreign_dish_checks_come_before_the_paid_bill(visit: Visit) -> None:
    pay(visit.waiter, visit.bill_id)
    missing = {"id": str(uuid.uuid4())}

    assert mark(visit.cook, missing, visit.order["items"], "ready").status_code == 404
    assert mark(visit.cook, visit.order, [{"id": str(uuid.uuid4())}], "ready").status_code == 422
    assert mark(visit.waiter, visit.order, visit.order["items"], "ready").status_code == 403


def test_orders_of_paid_bills_leave_the_kitchen_and_delivery_queues(visit: Visit) -> None:
    ok(mark(visit.cook, visit.order, visit.order["items"][:1], "ready"))
    assert len(queue(visit.cook, KITCHEN_URL)) == 1
    assert len(queue(visit.waiter, DELIVERIES_URL)) == 1

    pay(visit.waiter, visit.bill_id)

    assert queue(visit.cook, KITCHEN_URL) == []
    assert queue(visit.waiter, DELIVERIES_URL) == []


# --- Staff add dishes to an order of an open bill -------------------------------------------------


def test_a_waiter_adds_a_dish_at_the_menu_price_and_the_kitchen_gets_it(visit: Visit) -> None:
    added = add_dish(visit.waiter, visit.order, visit.items["suadero"], 2, note="no onion")

    assert added.status_code == 201
    order = added.json()
    assert order["id"] == visit.order["id"]
    assert [(i["name"], i["quantity"], i["status"], i["added_by"]) for i in order["items"]] == [
        ("Pastor", 1, "queued", "Tablet"),
        ("Pastor", 1, "queued", "Tablet"),
        ("Suadero", 2, "queued", "Staff"),
    ]
    assert order["items"][2]["note"] == "no onion"
    assert order["items"][2]["unit_price_cents"] == 2700
    assert order["total_cents"] == 2 * 2500 + 2 * 2700
    assert bill_total(visit.waiter, visit.bill_id) == 10400
    [card] = queue(visit.cook, KITCHEN_URL)
    assert [item["name"] for item in card["items"]] == ["Pastor", "Pastor", "Suadero"]
    assert "unit_price_cents" not in card["items"][2]


def test_an_admin_may_add_a_dish_but_not_the_kitchen_nor_the_table(visit: Visit) -> None:
    assert add_dish(visit.admin, visit.order, visit.items["pastor"]).status_code == 201
    assert add_dish(visit.cook, visit.order, visit.items["pastor"]).status_code == 403
    assert add_dish(visit.tablet, visit.order, visit.items["pastor"]).status_code == 403
    assert len(queue(visit.cook, KITCHEN_URL)[0]["items"]) == 3


def test_a_dish_that_is_not_on_the_menu_is_refused(visit: Visit) -> None:
    ok(visit.admin.patch(f"{ITEMS_URL}/{visit.items['suadero']}", json={"is_available": False}))

    refused = add_dish(visit.waiter, visit.order, visit.items["suadero"])

    assert refused.status_code == 409
    assert refused.json()["detail"] == "Some items are no longer available"
    assert refused.json()["unavailable_item_ids"] == [visit.items["suadero"]]
    assert bill_total(visit.waiter, visit.bill_id) == 5000


def test_no_dish_can_be_added_once_the_bill_is_paid(visit: Visit) -> None:
    pay(visit.waiter, visit.bill_id)

    refused = add_dish(visit.waiter, visit.order, visit.items["pastor"])

    assert (refused.status_code, refused.json()["detail"]) == (409, PAID)
    assert bill_total(visit.waiter, visit.bill_id) == 5000


def test_adding_a_dish_to_an_unknown_order_is_404(visit: Visit) -> None:
    refused = add_dish(visit.waiter, {"id": str(uuid.uuid4())}, visit.items["pastor"])

    assert (refused.status_code, refused.json()["detail"]) == (404, "Order not found")


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 1},
        {"item_id": str(uuid.uuid4()), "quantity": 0},
        {"item_id": str(uuid.uuid4()), "quantity": 51},
        {"item_id": str(uuid.uuid4()), "note": "x" * 201},
        {"item_id": str(uuid.uuid4()), "price_cents": 1},
    ],
)
def test_a_malformed_dish_is_422(visit: Visit, body: Json) -> None:
    assert visit.waiter.post(dishes_url(visit.order["id"]), json=body).status_code == 422


def test_staff_of_another_tenant_cannot_add_to_the_order(
    visit: Visit, new_client: ClientFactory, tenant_b: SeedResult
) -> None:
    other_admin = admin_of(new_client, "boss@example.com")
    other_waiter = staff_of(new_client, other_admin, "waiter.burger", "waiter")
    other_item = menu_items(other_admin)["pastor"]

    refused = add_dish(other_waiter, visit.order, other_item)

    assert (refused.status_code, refused.json()["detail"]) == (404, "Order not found")
    assert bill_total(visit.waiter, visit.bill_id) == 5000


def test_repeating_an_add_with_its_id_adds_the_dish_once(visit: Visit) -> None:
    dish_id = str(uuid.uuid4())
    first = add_dish(visit.waiter, visit.order, visit.items["suadero"], id=dish_id)
    again = add_dish(visit.waiter, visit.order, visit.items["suadero"], id=dish_id)

    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json() == first.json()
    assert bill_total(visit.waiter, visit.bill_id) == 7700


def test_an_id_already_used_by_something_else_is_409(
    visit: Visit, new_client: ClientFactory, tenant_b: SeedResult
) -> None:
    dish_id = str(uuid.uuid4())
    ok(add_dish(visit.waiter, visit.order, visit.items["suadero"], id=dish_id), 201)
    taken = "That id is already used by something else"

    other_data = add_dish(visit.waiter, visit.order, visit.items["pastor"], id=dish_id)
    second_order = send_order(visit.tablet, visit.items["pastor"], 1)
    other_order = add_dish(visit.waiter, second_order, visit.items["suadero"], id=dish_id)
    existing_dish = add_dish(visit.waiter, visit.order, visit.items["pastor"], id=visit.order["items"][0]["id"])
    other_admin = admin_of(new_client, "boss@example.com")
    other_tablet = tablet_of(new_client, created(create_table(other_admin, "Mesa 9")))
    other_items = menu_items(other_admin)
    other_tenant_order = send_order(other_tablet, other_items["pastor"], 1)
    other_tenant = add_dish(other_admin, other_tenant_order, other_items["suadero"], id=dish_id)

    for refused in (other_data, other_order, existing_dish, other_tenant):
        assert (refused.status_code, refused.json()["detail"]) == (409, taken)
    assert bill_total(visit.waiter, visit.bill_id) == 7700 + 2500


def test_paying_while_a_dish_is_added_never_loses_or_half_charges_it(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    waiter = staff_of(new_client, admin, "waiter.day", "waiter")
    other_waiter = staff_of(new_client, admin, "waiter.night", "waiter")
    for round_number in range(5):
        table = created(create_table(admin, f"Mesa {round_number + 10}"))
        tablet = tablet_of(new_client, table)
        bill_id = open_table(waiter, table)
        order = send_order(tablet, items["pastor"], 1)

        with ThreadPoolExecutor(2) as pool:
            paying = pool.submit(waiter.post, f"{BILLS_URL}/{bill_id}/payment", json={"method": "cash"})
            adding = pool.submit(add_dish, other_waiter, order, items["suadero"])
            paid, added = paying.result(), adding.result()

        assert paid.status_code == 200
        assert added.status_code in (201, 409), added.text
        expected = 2500 + (2700 if added.status_code == 201 else 0)
        assert paid_cents(bill_id) == expected
        assert bill_total(waiter, bill_id) == expected
        if added.status_code == 409:
            assert added.json()["detail"] == PAID
