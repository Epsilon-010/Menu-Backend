"""Deactivating a table with an unpaid bill never strands the bill: the staff still see it and charge or close it."""

from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import Json, ok
from tests.integration.modules.orders.test_guest_qr_api import guest_of, open_table
from tests.integration.modules.orders.test_kitchen_api import send_order
from tests.integration.modules.orders.test_ordering_api import (
    BILLS_URL,
    CART_URL,
    menu_items,
    staff_of,
    tables_overview,
)
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


def deactivate(admin: TestClient, table: Json) -> None:
    ok(admin.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False}))


def entry_for(staff: TestClient, table: Json) -> Json | None:
    return next((row for row in tables_overview(staff) if row["table_id"] == table["id"]), None)


def test_a_deactivated_table_with_an_unpaid_bill_stays_listed_until_it_is_paid(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    item = menu_items(admin)["pastor"]
    waiter = staff_of(new_client, admin, "waiter.bills", "waiter")
    table = created(create_table(admin, "Mesa 1"))
    tablet = tablet_of(new_client, table)
    send_order(tablet, item, 2)

    deactivate(admin, table)

    entry = entry_for(waiter, table)
    assert entry is not None
    assert entry["table_name"] == "Mesa 1"
    assert entry["bill"]["total_cents"] == 5000
    assert ok(waiter.get(f"{BILLS_URL}/{entry['bill']['id']}"))["table_name"] == "Mesa 1"

    paid = ok(waiter.post(f"{BILLS_URL}/{entry['bill']['id']}/payment", json={"method": "cash"}))

    assert (paid["total_cents"], paid["payment_method"], paid["closed_at"] is not None) == (5000, "cash", True)
    assert entry_for(waiter, table) is None


def test_a_deactivated_table_with_nothing_to_charge_is_closed_and_its_guests_stay_out(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    waiter = staff_of(new_client, admin, "waiter.bills", "waiter")
    table = created(create_table(admin, "Mesa 1"))
    bill_id = open_table(waiter, table)
    guest = guest_of(new_client, table["qr_token"])
    assert guest.get(CART_URL).status_code == 200

    deactivate(admin, table)
    assert entry_for(waiter, table) is not None

    assert waiter.post(f"{BILLS_URL}/{bill_id}/close").status_code == 204

    assert entry_for(waiter, table) is None
    assert guest.get(CART_URL).status_code == 401


def test_a_deactivated_table_without_a_bill_is_not_listed_and_listing_keeps_the_name_order(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    waiter = staff_of(new_client, admin, "waiter.bills", "waiter")
    empty = created(create_table(admin, "Mesa 1"))
    created(create_table(admin, "Mesa 2"))
    with_bill = created(create_table(admin, "Mesa 3"))
    open_table(waiter, with_bill)

    deactivate(admin, empty)
    deactivate(admin, with_bill)

    assert [(row["table_name"], row["bill"] is not None) for row in tables_overview(waiter)] == [
        ("Mesa 2", False),
        ("Mesa 3", True),
    ]


def test_an_inactive_table_cannot_be_opened(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    waiter = staff_of(new_client, admin, "waiter.bills", "waiter")
    table = created(create_table(admin, "Mesa 1"))
    deactivate(admin, table)

    response = waiter.post(BILLS_URL, json={"table_id": table["id"]})

    assert (response.status_code, response.json()["detail"]) == (404, "Table not found")
    assert tables_overview(waiter) == []


def test_another_tenant_never_sees_a_deactivated_table_with_a_bill(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    waiter = staff_of(new_client, admin, "waiter.bills", "waiter")
    table = created(create_table(admin, "Mesa 1"))
    bill_id = open_table(waiter, table)
    deactivate(admin, table)

    other = admin_of(new_client, "boss@example.com")

    assert tables_overview(other) == []
    assert other.post(f"{BILLS_URL}/{bill_id}/close").status_code == 404
