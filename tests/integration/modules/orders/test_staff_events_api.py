import json

from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import ok
from tests.integration.modules.orders.test_guest_qr_api import open_table, pay
from tests.integration.modules.orders.test_kitchen_api import mark, send_order
from tests.integration.modules.orders.test_ordering_api import add, menu_items, staff_of
from tests.integration.modules.orders.test_table_events_api import short_streams  # noqa: F401  (fixture)
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

STAFF_EVENTS_URL = "/api/v1/staff/events"
TABLE_EVENTS_URL = "/api/v1/table/events"


def received(client: TestClient, url: str) -> list[tuple[str, dict[str, object]]]:
    """(event, data) of every message the stream sends until it ends, from the start of the stream."""
    with client.stream("GET", url, headers={"Last-Event-ID": "0-0"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    messages = []
    for block in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in fields:
            messages.append((fields["event"], json.loads(fields["data"])))
    return messages


def test_the_staff_hear_orders_and_bills_of_every_table_but_no_carts_or_prices(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    item = menu_items(admin)["pastor"]
    table = created(create_table(admin, "Mesa 1"))
    tablet = tablet_of(new_client, table)
    cook = staff_of(new_client, admin, "cook.day", "kitchen")
    waiter = staff_of(new_client, admin, "waiter.day", "waiter")
    bill_id = open_table(waiter, table)
    order = send_order(tablet, item, 1)
    ok(mark(cook, order, order["items"], "ready"))
    ok(mark(waiter, order, order["items"], "delivered"))
    pay(waiter, bill_id)

    ids = {"table_id": table["id"], "order_id": order["id"]}
    expected = [
        ("bill.opened", {"table_id": table["id"]}),
        ("order.created", ids),
        ("order.updated", ids),
        ("order.updated", ids),
        ("bill.closed", {"table_id": table["id"]}),
    ]
    for staff in (cook, waiter, admin):
        assert received(staff, STAFF_EVENTS_URL) == expected


def test_a_table_hears_the_changes_of_its_own_orders_only(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    item = menu_items(admin)["pastor"]
    cook = staff_of(new_client, admin, "cook.day", "kitchen")
    mine = tablet_of(new_client, created(create_table(admin, "Mesa 1")))
    other = tablet_of(new_client, created(create_table(admin, "Mesa 2")))
    own_order = send_order(mine, item, 1)
    other_order = send_order(other, item, 1)
    ok(mark(cook, other_order, other_order["items"], "preparing"))  # another table: never heard here
    ok(mark(cook, own_order, own_order["items"], "cancelled", reason="Out of tortillas"))

    heard = [event for event, _data in received(mine, TABLE_EVENTS_URL)]

    assert heard == ["cart.updated", "order.created", "cart.updated", "order.updated"]
    assert received(other, TABLE_EVENTS_URL)[-1] == ("order.updated", {})


def test_the_staff_of_another_tenant_hear_nothing(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    tablet = tablet_of(new_client, created(create_table(admin, "Mesa 1")))
    items = menu_items(admin)
    ok(add(tablet, items["pastor"]))
    send_order(tablet, items["suadero"], 1)
    other_cook = staff_of(new_client, admin_of(new_client, "boss@example.com"), "cook.burger", "kitchen")

    assert received(other_cook, STAFF_EVENTS_URL) == []
