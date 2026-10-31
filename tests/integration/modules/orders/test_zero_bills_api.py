"""A bill with nothing to charge (no orders, or every dish cancelled) is closed, never paid for $0."""

import pytest
from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import Json, ok
from tests.integration.modules.orders.test_kitchen_api import mark, send_order
from tests.integration.modules.orders.test_ordering_api import BILLS_URL, menu_items, staff_of, tables_overview
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tablet_of,
    tenant_a,
)

NOTHING_TO_CHARGE = "This bill has nothing to charge; close the table instead"
NOTHING_TO_PAY = "There is nothing to pay yet"


class Table:
    def __init__(self, new_client: ClientFactory) -> None:
        self.admin = admin_of(new_client)
        self.items = menu_items(self.admin)
        self.tablet = tablet_of(new_client, created(create_table(self.admin, "Mesa 1")))
        self.cook = staff_of(new_client, self.admin, "cook.zero", "kitchen")
        self.waiter = staff_of(new_client, self.admin, "waiter.zero", "waiter")

    def bill(self) -> Json | None:
        bill: Json | None = tables_overview(self.waiter)[0]["bill"]
        return bill


@pytest.fixture
def table(new_client: ClientFactory, tenant_a: SeedResult) -> Table:
    return Table(new_client)


def cancel_all(table: Table, order: Json) -> None:
    ok(mark(table.cook, order, order["items"], "cancelled", reason="Out of stock"))


def pay(staff: TestClient, bill_id: str) -> object:
    return staff.post(f"{BILLS_URL}/{bill_id}/payment", json={"method": "cash"})


def test_a_bill_whose_dishes_were_all_cancelled_cannot_be_paid_but_closes(table: Table) -> None:
    cancel_all(table, send_order(table.tablet, table.items["pastor"], 2))
    bill = table.bill()
    assert bill is not None and bill["total_cents"] == 0

    refused = pay(table.waiter, bill["id"])

    assert (refused.status_code, refused.json()["detail"]) == (409, NOTHING_TO_CHARGE)  # type: ignore[attr-defined]
    assert table.bill() is not None  # still open: nothing changed
    assert table.waiter.post(f"{BILLS_URL}/{bill['id']}/close").status_code == 204
    assert table.bill() is None


def test_the_table_cannot_ask_for_a_bill_of_zero(table: Table) -> None:
    cancel_all(table, send_order(table.tablet, table.items["pastor"], 1))

    refused = table.tablet.post("/api/v1/table/bill-request")

    assert (refused.status_code, refused.json()["detail"]) == (409, NOTHING_TO_PAY)
    bill = table.bill()
    assert bill is not None and bill["bill_requested_at"] is None


def test_a_bill_with_something_left_to_charge_is_still_paid_not_closed(table: Table) -> None:
    order = send_order(table.tablet, table.items["pastor"], 2)
    ok(mark(table.cook, order, order["items"][:1], "cancelled", reason="Out of stock"))
    bill = table.bill()
    assert bill is not None

    refused = table.waiter.post(f"{BILLS_URL}/{bill['id']}/close")

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "A bill with orders is closed by registering its payment",
    )
    paid = ok(pay(table.waiter, bill["id"]))  # type: ignore[arg-type]
    assert (paid["total_cents"], paid["payment_method"]) == (2500, "cash")
