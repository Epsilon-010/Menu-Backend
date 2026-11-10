"""A payment can say which total the waiter saw: if the bill changed since, nothing is charged."""

import pytest
from fastapi.testclient import TestClient
from httpx import Response

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
    tenant_b,
)

BILL_CHANGED = "The bill changed, review it"


class Table:
    def __init__(self, new_client: ClientFactory) -> None:
        self.admin = admin_of(new_client)
        self.items = menu_items(self.admin)
        self.tablet = tablet_of(new_client, created(create_table(self.admin, "Mesa 1")))
        self.waiter = staff_of(new_client, self.admin, "waiter.pay", "waiter")
        self.cook = staff_of(new_client, self.admin, "cook.pay", "kitchen")

    def bill(self) -> Json:
        bill: Json = tables_overview(self.waiter)[0]["bill"]
        return bill


@pytest.fixture
def table(new_client: ClientFactory, tenant_a: SeedResult) -> Table:
    return Table(new_client)


def pay(staff: TestClient, bill_id: str, **body: object) -> Response:
    return staff.post(f"{BILLS_URL}/{bill_id}/payment", json={"method": "cash", **body})


def test_a_payment_of_a_total_that_changed_is_refused_and_charges_nothing(table: Table) -> None:
    send_order(table.tablet, table.items["pastor"], 1)
    seen = table.bill()
    send_order(table.tablet, table.items["pastor"], 1)  # another round while the waiter had the old total

    refused = pay(table.waiter, seen["id"], expected_total_cents=seen["total_cents"])

    assert refused.status_code == 409
    assert refused.headers["content-type"] == "application/problem+json"
    assert refused.json()["detail"] == BILL_CHANGED
    still_open = table.bill()
    assert still_open["id"] == seen["id"]
    assert still_open["closed_at"] is None and still_open["payment_method"] is None
    assert still_open["total_cents"] == 2 * seen["total_cents"]
    assert ok(table.tablet.get("/api/v1/table/orders"))  # the table keeps its visit


def test_a_payment_of_the_total_the_waiter_saw_goes_through(table: Table) -> None:
    send_order(table.tablet, table.items["pastor"], 2)
    seen = table.bill()

    paid = ok(pay(table.waiter, seen["id"], expected_total_cents=seen["total_cents"]))

    assert (paid["total_cents"], paid["payment_method"], paid["closed_at"] is not None) == (
        seen["total_cents"],
        "cash",
        True,
    )
    assert tables_overview(table.waiter)[0]["bill"] is None


def test_a_payment_without_an_expected_total_behaves_as_before(table: Table) -> None:
    send_order(table.tablet, table.items["pastor"], 1)
    seen = table.bill()
    send_order(table.tablet, table.items["pastor"], 1)

    paid = ok(pay(table.waiter, seen["id"]))

    assert (paid["total_cents"], paid["payment_method"]) == (2 * seen["total_cents"], "cash")


def test_a_bill_cancelled_down_to_zero_is_a_changed_bill_for_a_stale_total(table: Table) -> None:
    order = send_order(table.tablet, table.items["pastor"], 1)
    seen = table.bill()
    ok(mark(table.cook, order, order["items"], "cancelled", reason="Out of stock"))

    refused = pay(table.waiter, seen["id"], expected_total_cents=seen["total_cents"])

    assert (refused.status_code, refused.json()["detail"]) == (409, BILL_CHANGED)


def test_an_empty_bill_still_has_nothing_to_charge_when_the_total_matches(table: Table) -> None:
    order = send_order(table.tablet, table.items["pastor"], 1)
    ok(mark(table.cook, order, order["items"], "cancelled", reason="Out of stock"))
    bill = table.bill()

    refused = pay(table.waiter, bill["id"], expected_total_cents=0)

    assert refused.status_code == 409
    assert refused.json()["detail"] == "This bill has nothing to charge; close the table instead"


def test_an_invalid_expected_total_is_a_422(table: Table) -> None:
    send_order(table.tablet, table.items["pastor"], 1)
    bill = table.bill()

    for value in (-1, "many", 1.5, True):
        assert pay(table.waiter, bill["id"], expected_total_cents=value).status_code == 422
    assert table.bill()["id"] == bill["id"]


def test_another_tenant_never_learns_a_bill_exists_from_the_expected_total(
    new_client: ClientFactory, table: Table, tenant_b: SeedResult
) -> None:
    send_order(table.tablet, table.items["pastor"], 1)
    bill = table.bill()
    other = admin_of(new_client, "boss@example.com")

    refused = pay(other, bill["id"], expected_total_cents=bill["total_cents"] + 1)

    assert (refused.status_code, refused.json()["detail"]) == (404, "Bill not found")
    assert table.bill()["id"] == bill["id"]
