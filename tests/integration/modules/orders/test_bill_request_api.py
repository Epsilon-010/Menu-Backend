import pytest
from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import Json, ok
from tests.integration.modules.orders.test_guest_qr_api import guest_of, open_table, pay
from tests.integration.modules.orders.test_kitchen_api import send_order
from tests.integration.modules.orders.test_ordering_api import BILLS_URL, menu_items, staff_of, tables_overview
from tests.integration.modules.orders.test_staff_events_api import STAFF_EVENTS_URL, TABLE_EVENTS_URL, received
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

REQUEST_URL = "/api/v1/table/bill-request"
NOTHING_TO_PAY = "There is nothing to pay yet"


def dismiss_url(bill_id: str) -> str:
    return f"{BILLS_URL}/{bill_id}/request"


def requested_at(client: TestClient) -> str | None:
    return ok(client.get(REQUEST_URL))["requested_at"]  # type: ignore[return-value]


def card(staff: TestClient, table: Json) -> Json:
    return next(overview for overview in tables_overview(staff) if overview["table_id"] == table["id"])


class Visit:
    """Tenant A: an open table with one order, a waiter, a cook and a guest who joined by QR."""

    def __init__(self, new_client: ClientFactory) -> None:
        self.new_client = new_client
        self.admin = admin_of(new_client)
        self.items = menu_items(self.admin)
        self.table = created(create_table(self.admin, "Mesa 1"))
        self.tablet = tablet_of(new_client, self.table)
        self.waiter = staff_of(new_client, self.admin, "waiter.day", "waiter")
        self.cook = staff_of(new_client, self.admin, "cook.day", "kitchen")
        self.bill_id = open_table(self.waiter, self.table)
        self.guest = guest_of(new_client, self.table["qr_token"])
        self.order = send_order(self.tablet, self.items["pastor"], 1)


@pytest.fixture
def visit(new_client: ClientFactory, tenant_a: SeedResult) -> Visit:
    return Visit(new_client)


def test_a_guest_asks_for_the_bill_and_everyone_at_the_table_and_the_waiter_see_it(visit: Visit) -> None:
    assert requested_at(visit.tablet) is None
    assert card(visit.waiter, visit.table)["bill"]["bill_requested_at"] is None

    asked = ok(visit.guest.post(REQUEST_URL))

    assert asked["requested_at"] is not None
    assert requested_at(visit.tablet) == asked["requested_at"]
    assert requested_at(visit.guest) == asked["requested_at"]
    assert card(visit.waiter, visit.table)["bill"]["bill_requested_at"] == asked["requested_at"]
    assert ok(visit.admin.get(f"{BILLS_URL}/{visit.bill_id}"))["bill_requested_at"] == asked["requested_at"]


def test_asking_again_keeps_the_first_request_and_sends_a_single_alert(visit: Visit) -> None:
    first = ok(visit.tablet.post(REQUEST_URL))
    again = ok(visit.guest.post(REQUEST_URL))

    assert again == first
    heard = [event for event, _data in received(visit.waiter, STAFF_EVENTS_URL)]
    assert heard.count("bill.requested") == 1


def test_the_table_cancels_its_request_and_cancelling_twice_is_fine(visit: Visit) -> None:
    ok(visit.tablet.post(REQUEST_URL))

    assert visit.guest.delete(REQUEST_URL).status_code == 204
    assert visit.tablet.delete(REQUEST_URL).status_code == 204

    assert requested_at(visit.tablet) is None
    assert card(visit.waiter, visit.table)["bill"]["bill_requested_at"] is None
    # After cancelling it can be asked again.
    assert ok(visit.tablet.post(REQUEST_URL))["requested_at"] is not None


def test_the_waiter_attends_the_request(visit: Visit) -> None:
    ok(visit.guest.post(REQUEST_URL))

    assert visit.waiter.delete(dismiss_url(visit.bill_id)).status_code == 204
    assert visit.admin.delete(dismiss_url(visit.bill_id)).status_code == 204

    assert requested_at(visit.guest) is None
    assert card(visit.waiter, visit.table)["bill"]["bill_requested_at"] is None


def test_staff_and_the_table_hear_the_request_and_its_end_but_other_tables_do_not(visit: Visit) -> None:
    other = tablet_of(visit.new_client, created(create_table(visit.admin, "Mesa 2")))
    ok(visit.guest.post(REQUEST_URL))
    assert visit.tablet.delete(REQUEST_URL).status_code == 204
    ok(visit.tablet.post(REQUEST_URL))
    assert visit.waiter.delete(dismiss_url(visit.bill_id)).status_code == 204

    table = {"table_id": visit.table["id"]}
    expected = [("bill.requested", table), ("bill.request_cleared", table)] * 2
    for staff in (visit.waiter, visit.admin, visit.cook):
        heard = [message for message in received(staff, STAFF_EVENTS_URL) if message[0].startswith("bill.request")]
        assert heard == expected
    table_heard = [event for event, _data in received(visit.tablet, TABLE_EVENTS_URL)]
    assert [event for event in table_heard if event.startswith("bill.request")] == [
        "bill.requested",
        "bill.request_cleared",
    ] * 2
    assert not [event for event, _data in received(other, TABLE_EVENTS_URL) if event.startswith("bill.request")]


def test_paying_ends_the_request_and_the_next_visit_starts_without_one(visit: Visit) -> None:
    ok(visit.tablet.post(REQUEST_URL))
    pay(visit.waiter, visit.bill_id)

    assert requested_at(visit.tablet) is None
    assert ok(visit.waiter.get(f"{BILLS_URL}/{visit.bill_id}"))["bill_requested_at"] is None
    assert visit.waiter.delete(dismiss_url(visit.bill_id)).status_code == 404
    next_bill = open_table(visit.waiter, visit.table)
    assert card(visit.waiter, visit.table)["bill"]["id"] == next_bill
    assert card(visit.waiter, visit.table)["bill"]["bill_requested_at"] is None


def test_there_is_nothing_to_ask_for_without_an_order(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin, "Mesa 1"))
    tablet = tablet_of(new_client, table)
    waiter = staff_of(new_client, admin, "waiter.day", "waiter")

    without_bill = tablet.post(REQUEST_URL)
    open_table(waiter, table)
    guest = guest_of(new_client, table["qr_token"])
    without_orders = guest.post(REQUEST_URL)

    for refused in (without_bill, without_orders):
        assert (refused.status_code, refused.json()["detail"]) == (409, NOTHING_TO_PAY)
    assert requested_at(tablet) is None
    assert tablet.delete(REQUEST_URL).status_code == 204


def test_a_guest_whose_visit_ended_can_neither_ask_nor_cancel(visit: Visit) -> None:
    pay(visit.waiter, visit.bill_id)
    open_table(visit.waiter, visit.table)

    for response in (visit.guest.get(REQUEST_URL), visit.guest.post(REQUEST_URL), visit.guest.delete(REQUEST_URL)):
        assert response.status_code == 401


def test_only_the_table_asks_and_only_waiters_and_admins_attend(visit: Visit) -> None:
    for staff in (visit.admin, visit.waiter, visit.cook):
        assert staff.post(REQUEST_URL).status_code == 403
        assert staff.delete(REQUEST_URL).status_code == 403
    ok(visit.tablet.post(REQUEST_URL))
    for diner in (visit.cook, visit.tablet, visit.guest):
        assert diner.delete(dismiss_url(visit.bill_id)).status_code == 403

    assert requested_at(visit.tablet) is not None


def test_another_tenant_cannot_see_or_attend_the_request(
    new_client: ClientFactory, visit: Visit, tenant_b: SeedResult
) -> None:
    ok(visit.tablet.post(REQUEST_URL))
    stranger = admin_of(new_client, "boss@example.com")

    assert stranger.delete(dismiss_url(visit.bill_id)).status_code == 404
    assert all(overview["table_id"] != visit.table["id"] for overview in tables_overview(stranger))
    assert requested_at(visit.tablet) is not None
