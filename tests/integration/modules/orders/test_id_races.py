"""Races on a client-chosen id between two tables.

The table lock only serializes one table, so two tables (or a table and a waiter at another table) could both
see an id as free. Claiming an id takes a lock on the id itself: the second request waits, then sees it taken
(409), never a 500 and never one id in two places."""

import asyncio
import time
import uuid
from typing import Any

import pytest

from app.modules.orders.infrastructure.repository import SqlAlchemyCartRepository, SqlAlchemyOrderRepository
from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import ok
from tests.integration.modules.orders.test_guest_races import in_background
from tests.integration.modules.orders.test_ordering_api import ORDERS_URL, add, cart, menu_items, submit
from tests.integration.modules.orders.test_paid_bills_api import add_dish
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tablet_of,
    tenant_a,
)

TAKEN = (409, "That id is already used by something else")
HOLD = 0.6


def slowed(monkeypatch: pytest.MonkeyPatch, owner: type, name: str) -> None:
    """The first call waits before writing, holding its locks while the other request arrives."""
    original = getattr(owner, name)
    calls = {"count": 0}

    async def slow(self: Any, *args: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            await asyncio.sleep(HOLD)
        return await original(self, *args)

    monkeypatch.setattr(owner, name, slow)


def outcome(response: Any) -> tuple[int, str | None]:
    body = response.json()
    return response.status_code, body.get("detail") if isinstance(body, dict) else None


def test_two_tables_adding_a_line_with_the_same_id_at_once_get_one_line_and_a_409(
    new_client: ClientFactory, tenant_a: SeedResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    first, second = (tablet_of(new_client, created(create_table(admin, name))) for name in ("Table 1", "Table 2"))
    line_id = str(uuid.uuid4())
    slowed(monkeypatch, SqlAlchemyCartRepository, "add_line")

    thread, results = in_background(lambda: add(first, items["pastor"], id=line_id))
    time.sleep(HOLD / 3)
    late = add(second, items["pastor"], id=line_id)
    thread.join()

    assert results[0].status_code == 200, results[0].text
    assert outcome(late) == TAKEN
    assert [line["id"] for line in cart(first)["lines"]] == [line_id]
    assert cart(second)["lines"] == []


def test_two_tables_sending_orders_with_the_same_id_at_once_make_one_order_and_a_409(
    new_client: ClientFactory, tenant_a: SeedResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    first, second = (tablet_of(new_client, created(create_table(admin, name))) for name in ("Table 1", "Table 2"))
    for tablet in (first, second):
        ok(add(tablet, items["pastor"]))
    order_id = str(uuid.uuid4())
    slowed(monkeypatch, SqlAlchemyOrderRepository, "add")

    thread, results = in_background(lambda: submit(first, cart(first)["version"], id=order_id))
    time.sleep(HOLD / 3)
    late = submit(second, cart(second)["version"], id=order_id)
    thread.join()

    assert results[0].status_code == 201, results[0].text
    assert outcome(late) == TAKEN
    assert [order["id"] for order in ok(first.get(ORDERS_URL))] == [order_id]
    assert ok(second.get(ORDERS_URL)) == []
    assert len(cart(second)["lines"]) == 1


def test_a_cart_line_and_a_dish_added_at_another_table_never_share_an_id(
    new_client: ClientFactory, tenant_a: SeedResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    diners, served = (tablet_of(new_client, created(create_table(admin, name))) for name in ("Table 1", "Table 2"))
    ok(add(served, items["pastor"]))
    order = ok(submit(served, cart(served)["version"]), 201)
    shared_id = str(uuid.uuid4())
    slowed(monkeypatch, SqlAlchemyCartRepository, "add_line")

    thread, results = in_background(lambda: add(diners, items["pastor"], id=shared_id))
    time.sleep(HOLD / 3)
    dish = add_dish(admin, order, items["pastor"], id=shared_id)
    thread.join()

    assert results[0].status_code == 200, results[0].text
    assert outcome(dish) == TAKEN
    # The line keeps its id when sent, and nothing else holds it: the table can still order.
    sent = ok(submit(diners, cart(diners)["version"]), 201)
    assert [item["id"] for item in sent["items"]] == [shared_id]
