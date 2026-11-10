"""Adding to the cart reads the requested items, never the tenant's whole catalog; the rules stay the menu's."""

import pytest

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import CATEGORIES_URL, ITEMS_URL, ok
from tests.integration.modules.orders.test_ordering_api import add, cart, menu_items
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
from tests.integration.query_log import recorded_statements

CATALOG_TABLES = ("FROM categories", "FROM items", "FROM modifier_groups")


def _catalog_reads(statements: list[str]) -> list[str]:
    return [s for s in statements if s.lstrip().startswith("SELECT") and any(t in s for t in CATALOG_TABLES)]


def test_adding_a_line_reads_only_the_requested_item(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))

    with recorded_statements() as statements:
        ok(add(tablet, items["pastor"]))

    reads = _catalog_reads(statements)
    assert reads
    for statement in reads:
        assert " IN (" in statement, statement  # always by ids, never a tenant-wide scan


def test_reading_the_cart_reads_only_the_items_in_it(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    ok(add(tablet, items["pastor"]))

    with recorded_statements() as statements:
        shown = cart(tablet)

    assert [line["name"] for line in shown["lines"]] == ["Pastor"]
    for statement in _catalog_reads(statements):
        assert " IN (" in statement, statement


def test_an_item_of_a_hidden_category_cannot_be_ordered(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    tacos = ok(admin.get(CATEGORIES_URL))[0]["id"]  # type: ignore[index]
    ok(admin.patch(f"{CATEGORIES_URL}/{tacos}", json={"is_visible": False}))

    refused = add(tablet, items["pastor"])

    assert refused.status_code == 409
    assert refused.json()["detail"] == "Some items are no longer available"
    assert refused.json()["unavailable_item_ids"] == [items["pastor"]]
    assert cart(tablet)["lines"] == []


def test_an_unavailable_item_cannot_be_ordered(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    ok(admin.patch(f"{ITEMS_URL}/{items['pastor']}", json={"is_available": False}))

    refused = add(tablet, items["pastor"])

    assert refused.status_code == 409
    assert refused.json()["unavailable_item_ids"] == [items["pastor"]]


def test_an_item_of_another_tenant_cannot_be_ordered(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    theirs = menu_items(admin_of(new_client, "boss@example.com"))["pastor"]

    refused = add(tablet, theirs)

    assert refused.status_code == 409
    assert refused.json()["unavailable_item_ids"] == [theirs]
    assert cart(tablet)["lines"] == []


@pytest.mark.parametrize("quantity", [1, 3])
def test_a_visible_available_item_still_prices_the_cart(
    new_client: ClientFactory, tenant_a: SeedResult, quantity: int
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))

    shown = ok(add(tablet, items["pastor"], quantity))

    assert shown["total_cents"] == 2500 * quantity
    assert shown["lines"][0]["available"] is True
