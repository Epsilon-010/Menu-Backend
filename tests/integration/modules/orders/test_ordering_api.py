import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import login
from tests.integration.modules.catalog.test_catalog_api import ITEMS_URL, Json, create_category, create_item, ok
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, create_member
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    TABLES_URL,
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tablet_of,
    tenant_a,
    tenant_b,
)

CART_URL = "/api/v1/table/cart"
LINES_URL = f"{CART_URL}/lines"
ORDERS_URL = "/api/v1/table/orders"
BILLS_URL = "/api/v1/bills"


def menu_items(admin: TestClient) -> dict[str, str]:
    tacos = ok(create_category(admin, "Tacos"), 201)["id"]
    return {
        "pastor": ok(create_item(admin, tacos, "Pastor", 2500), 201)["id"],
        "suadero": ok(create_item(admin, tacos, "Suadero", 2700), 201)["id"],
    }


def add(client: TestClient, item_id: str, quantity: int = 1, **extra: Any) -> Response:
    return client.post(LINES_URL, json={"item_id": item_id, "quantity": quantity, **extra})


def cart(client: TestClient) -> Json:
    return ok(client.get(CART_URL))


def submit(client: TestClient, version: int, **extra: Any) -> Response:
    return client.post(ORDERS_URL, json={"cart_version": version, **extra})


def staff_of(new_client: ClientFactory, admin: TestClient, username: str, role: str) -> TestClient:
    create_member(admin, username, role)
    client = new_client()
    assert login(client, username=username, password=STAFF_PASSWORD).status_code == 200
    return client


def tables_overview(staff: TestClient) -> list[Json]:
    body: list[Json] = ok(staff.get(f"{BILLS_URL}/tables"))  # type: ignore[assignment]
    return body


# --- Shared cart, one order per send ----------------------------------------------------------


def test_everyone_at_the_table_builds_one_cart_and_one_send_makes_one_order(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    first, second = tablet_of(new_client, table), tablet_of(new_client, table)

    ok(add(first, items["pastor"], 2, note="sin cebolla"))
    seen_by_second = ok(add(second, items["suadero"]))

    assert cart(first) == seen_by_second
    assert seen_by_second["version"] == 2
    assert [(line["name"], line["quantity"], line["subtotal_cents"]) for line in seen_by_second["lines"]] == [
        ("Pastor", 2, 5000),
        ("Suadero", 1, 2700),
    ]
    assert seen_by_second["total_cents"] == 7700

    order = ok(submit(second, seen_by_second["version"]), 201)

    assert order["number"] == 1
    assert order["status"] == "queued"
    assert order["total_cents"] == 7700
    assert [(item["name"], item["quantity"], item["note"]) for item in order["items"]] == [
        ("Pastor", 2, "sin cebolla"),
        ("Suadero", 1, ""),
    ]
    # The next round starts empty, and both see the order already sent.
    assert cart(first) == {"version": 3, "lines": [], "total_cents": 0}
    assert ok(first.get(ORDERS_URL)) == [order]


def test_a_send_confirmed_on_an_older_cart_is_refused_and_creates_nothing(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    sender, other = tablet_of(new_client, table), tablet_of(new_client, table)
    reviewed = ok(add(sender, items["pastor"]))["version"]

    ok(add(other, items["suadero"]))  # while the sender reviews the summary
    refused = submit(sender, reviewed)

    assert refused.status_code == 409
    assert refused.json()["detail"] == "The order changed, review it"
    assert ok(sender.get(ORDERS_URL)) == []
    assert len(cart(sender)["lines"]) == 2
    assert submit(sender, cart(sender)["version"]).status_code == 201


def test_two_people_sending_at_once_make_a_single_order(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    senders = [tablet_of(new_client, table) for _ in range(4)]
    version = ok(add(senders[0], items["pastor"]))["version"]

    with ThreadPoolExecutor(len(senders)) as pool:
        results = list(pool.map(lambda client: submit(client, version), senders))

    assert sorted(result.status_code for result in results) == [201, 409, 409, 409]
    assert len(ok(senders[0].get(ORDERS_URL))) == 1


def test_repeating_a_send_with_its_id_returns_the_same_order(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    line_id, order_id = str(uuid.uuid4()), str(uuid.uuid4())
    version = ok(add(tablet, items["pastor"], id=line_id))["version"]
    assert ok(add(tablet, items["pastor"], id=line_id))["version"] == version  # a repeated add adds nothing

    first = ok(submit(tablet, version, id=order_id), 201)
    again = ok(submit(tablet, version, id=order_id), 201)

    assert again == first
    # The line was sent in that order: repeating its add now must not put it in the next round.
    assert add(tablet, items["pastor"], id=line_id).status_code == 409
    assert cart(tablet)["lines"] == []


def test_prices_always_come_from_the_menu_at_the_moment_of_sending(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))

    assert add(tablet, items["pastor"], price_cents=1).status_code == 422
    ok(add(tablet, items["pastor"], 2))
    ok(admin.patch(f"{ITEMS_URL}/{items['pastor']}", json={"price_cents": 3000}))
    version = cart(tablet)["version"]
    assert submit(tablet, version, total_cents=1).status_code == 422

    order = ok(submit(tablet, version), 201)

    assert order["items"][0]["unit_price_cents"] == 3000
    assert order["total_cents"] == 6000


def test_items_that_left_the_menu_block_the_send_until_removed(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    ok(add(tablet, items["pastor"]))
    line = ok(add(tablet, items["suadero"]))["lines"][1]
    ok(admin.patch(f"{ITEMS_URL}/{items['suadero']}", json={"is_available": False}))

    shown = cart(tablet)
    assert [(entry["name"], entry["available"]) for entry in shown["lines"]] == [("Pastor", True), ("Suadero", False)]
    assert shown["total_cents"] == 2500
    refused = submit(tablet, shown["version"])
    assert refused.status_code == 409
    assert refused.json()["unavailable_item_ids"] == [items["suadero"]]
    assert add(tablet, items["suadero"]).status_code == 409

    version = ok(tablet.delete(f"{LINES_URL}/{line['id']}"))["version"]
    assert ok(submit(tablet, version), 201)["total_cents"] == 2500


def test_cart_input_is_validated(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))

    assert add(tablet, items["pastor"], 0).status_code == 422
    assert add(tablet, items["pastor"], 51).status_code == 422
    assert add(tablet, items["pastor"], note="x" * 201).status_code == 422
    assert add(tablet, str(uuid.uuid4())).status_code == 409
    empty = submit(tablet, 0)
    assert (empty.status_code, empty.json()["detail"]) == (409, "The order is empty")
    line = ok(add(tablet, items["pastor"]))["lines"][0]
    changed = ok(tablet.patch(f"{LINES_URL}/{line['id']}", json={"quantity": 3, "note": "bien dorado"}))
    assert (changed["lines"][0]["quantity"], changed["lines"][0]["note"]) == (3, "bien dorado")
    assert tablet.patch(f"{LINES_URL}/{uuid.uuid4()}", json={"quantity": 2}).status_code == 404


def test_a_table_never_sees_nor_changes_another_table_or_tenant_cart(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    mesa_4 = tablet_of(new_client, created(create_table(admin, "Mesa 4")))
    mesa_5 = tablet_of(new_client, created(create_table(admin, "Mesa 5")))
    other_admin = admin_of(new_client, "boss@example.com")
    other_tenant = tablet_of(new_client, created(create_table(other_admin)))
    line = ok(add(mesa_4, items["pastor"]))["lines"][0]
    ok(submit(mesa_4, cart(mesa_4)["version"]), 201)
    line = ok(add(mesa_4, items["pastor"]))["lines"][0]

    for intruder in (mesa_5, other_tenant):
        assert cart(intruder)["lines"] == []
        assert ok(intruder.get(ORDERS_URL)) == []
        assert intruder.patch(f"{LINES_URL}/{line['id']}", json={"quantity": 5}).status_code == 404
        assert intruder.delete(f"{LINES_URL}/{line['id']}").status_code == 404
    # Another tenant's items are not on this tenant's menu.
    assert add(other_tenant, items["pastor"]).status_code == 409
    assert cart(mesa_4)["lines"][0]["quantity"] == 1


def test_only_tables_order_and_only_waiters_and_admins_handle_bills(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    waiter = staff_of(new_client, admin, "mesero", "waiter")
    cook = staff_of(new_client, admin, "cocina", "kitchen")
    bill_id = ok(waiter.post(BILLS_URL, json={"table_id": table["id"]}))["id"]

    for staff in (admin, waiter, cook):
        assert staff.get(CART_URL).status_code == 403
        assert add(staff, items["pastor"]).status_code == 403
        assert submit(staff, 0).status_code == 403
    for caller in (tablet, cook):
        assert caller.get(f"{BILLS_URL}/tables").status_code == 403
        assert caller.post(BILLS_URL, json={"table_id": table["id"]}).status_code == 403
        assert caller.get(f"{BILLS_URL}/{bill_id}").status_code == 403
        assert caller.post(f"{BILLS_URL}/{bill_id}/payment", json={"method": "cash"}).status_code == 403
    anonymous = new_client()
    assert anonymous.get(CART_URL).status_code == 401
    assert anonymous.get(f"{BILLS_URL}/tables").status_code == 401


# --- Bills: open the table, pay, next visit ------------------------------------------------------


def test_the_waiter_opens_the_table_sees_its_bill_and_payment_closes_it(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin, "Mesa 4"))
    created(create_table(admin, "Mesa 5"))
    tablet = tablet_of(new_client, table)
    waiter = staff_of(new_client, admin, "mesero", "waiter")

    opened = ok(waiter.post(BILLS_URL, json={"table_id": table["id"]}))
    assert ok(waiter.post(BILLS_URL, json={"table_id": table["id"]}))["id"] == opened["id"]  # already open
    ok(add(tablet, items["pastor"], 2))
    ok(submit(tablet, cart(tablet)["version"]), 201)
    ok(add(tablet, items["suadero"]))
    ok(submit(tablet, cart(tablet)["version"]), 201)
    ok(add(tablet, items["pastor"]))  # never sent

    overview = tables_overview(waiter)
    assert [(entry["table_name"], entry["bill"] is not None) for entry in overview] == [
        ("Mesa 4", True),
        ("Mesa 5", False),
    ]
    bill = overview[0]["bill"]
    assert (bill["id"], bill["total_cents"], [order["number"] for order in bill["orders"]]) == (opened["id"], 7700, [1, 2])

    paid = ok(waiter.post(f"{BILLS_URL}/{opened['id']}/payment", json={"method": "card"}))

    assert (paid["payment_method"], paid["total_cents"], paid["closed_at"] is not None) == ("card", 7700, True)
    assert tables_overview(waiter)[0]["bill"] is None
    assert cart(tablet)["lines"] == []  # the unsent line was discarded with the visit
    assert ok(tablet.get(ORDERS_URL)) == []
    assert waiter.post(f"{BILLS_URL}/{opened['id']}/payment", json={"method": "cash"}).status_code == 404

    # The tablet's next order opens a new bill on its own.
    ok(add(tablet, items["pastor"]))
    order = ok(submit(tablet, cart(tablet)["version"]), 201)
    new_bill = tables_overview(waiter)[0]["bill"]
    assert new_bill["id"] != opened["id"]
    assert [entry["id"] for entry in new_bill["orders"]] == [order["id"]]


def test_a_bill_closes_without_payment_only_when_it_has_no_orders(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    empty = ok(admin.post(BILLS_URL, json={"table_id": table["id"]}))["id"]

    assert admin.post(f"{BILLS_URL}/{empty}/close").status_code == 204
    with_orders = ok(admin.post(BILLS_URL, json={"table_id": table["id"]}))["id"]
    ok(add(tablet, items["pastor"]))
    ok(submit(tablet, cart(tablet)["version"]), 201)

    refused = admin.post(f"{BILLS_URL}/{with_orders}/close")
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "A bill with orders is closed by registering its payment",
    )
    assert admin.post(f"{BILLS_URL}/{uuid.uuid4()}/close").status_code == 404
    assert admin.post(BILLS_URL, json={"table_id": str(uuid.uuid4())}).status_code == 404
    assert admin.post(f"{BILLS_URL}/{with_orders}/payment", json={"method": "bitcoin"}).status_code == 422


def test_a_tenant_never_sees_nor_pays_another_tenant_bills(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    bill_id = ok(admin.post(BILLS_URL, json={"table_id": table["id"]}))["id"]
    other = admin_of(new_client, "boss@example.com")

    assert tables_overview(other) == []
    assert other.get(f"{BILLS_URL}/{bill_id}").status_code == 404
    assert other.post(f"{BILLS_URL}/{bill_id}/payment", json={"method": "cash"}).status_code == 404
    assert other.post(f"{BILLS_URL}/{bill_id}/close").status_code == 404
    assert other.post(BILLS_URL, json={"table_id": table["id"]}).status_code == 404
    assert ok(admin.get(f"{BILLS_URL}/{bill_id}"))["closed_at"] is None


def test_a_signed_out_tablet_can_no_longer_order(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    ok(add(tablet, items["pastor"]))

    ok(admin.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False}))

    assert add(tablet, items["pastor"]).status_code == 401
    assert submit(tablet, 1).status_code == 401
