import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.modules.orders.infrastructure import events
from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import ok
from tests.integration.modules.orders.test_guest_qr_api import guest_of, open_table, pay
from tests.integration.modules.orders.test_ordering_api import add, cart, menu_items, staff_of, submit
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tablet_of,
    tenant_a,
)

EVENTS_URL = "/api/v1/table/events"


@pytest.fixture(autouse=True)
def short_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "STREAM_SECONDS", 1.5)
    monkeypatch.setattr(events, "BLOCK_MS", 200)


def received(client: TestClient, last_event_id: str | None = "0-0") -> list[tuple[str, dict[str, int]]]:
    """(event, data) of every message the stream sends until it ends."""
    headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
    with client.stream("GET", EVENTS_URL, headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())
    messages = []
    for block in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in fields:
            messages.append((fields["event"], json.loads(fields["data"])))
    return messages


def test_everyone_at_the_table_hears_its_cart_and_orders_and_nothing_else(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin, "Mesa 4"))
    other = tablet_of(new_client, created(create_table(admin, "Mesa 5")))
    tablet = tablet_of(new_client, table)
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    ok(add(other, items["pastor"]))  # another table: never heard here
    ok(add(guest, items["pastor"]))
    ok(add(tablet, items["suadero"]))
    ok(submit(guest, cart(guest)["version"]), 201)

    expected = [
        ("bill.opened", {}),
        ("cart.updated", {"cart_version": 1}),
        ("cart.updated", {"cart_version": 2}),
        ("order.created", {}),
        ("cart.updated", {"cart_version": 3}),
    ]
    assert received(tablet) == expected
    assert received(guest) == expected


def test_a_change_reaches_an_open_stream_right_away(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    listener, other_phone = tablet_of(new_client, table), tablet_of(new_client, table)

    def add_soon() -> None:
        time.sleep(0.4)
        ok(add(other_phone, items["pastor"]))

    adder = threading.Thread(target=add_soon)
    adder.start()
    messages = received(listener, last_event_id=None)  # from now on
    adder.join()

    assert messages == [("cart.updated", {"cart_version": 1})]


def test_a_guest_stream_ends_with_the_visit_and_cannot_be_opened_again(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    bill_id = open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])

    def pay_soon() -> None:
        time.sleep(0.3)
        pay(admin, bill_id)

    payer = threading.Thread(target=pay_soon)
    payer.start()
    started = time.monotonic()
    messages = received(guest, last_event_id=None)
    payer.join()

    assert messages[-1] == ("bill.closed", {})
    assert time.monotonic() - started < 1.2  # cut off right away, not at the end of the stream
    assert guest.get(EVENTS_URL).status_code == 401


def test_only_the_table_and_its_guests_open_the_stream(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    waiter = staff_of(new_client, admin, "mesero", "waiter")

    assert admin.get(EVENTS_URL).status_code == 403
    assert waiter.get(EVENTS_URL).status_code == 403
    assert new_client().get(EVENTS_URL).status_code == 401
