"""Guests who join a table by its QR: many phones, one shared cart, and no way back in once the visit ends.

"nadie pueda cceder depues de ir aunque haya abiero la app o la abra desde su casa y siga haciendo
pedidos a nomreb de esa mesa depues de dias de haber uido"
"""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response
from redis import Redis
from sqlalchemy import update

from app.modules.orders.infrastructure.models import GuestModel
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import claims_for, me, sign
from tests.integration.modules.catalog.test_catalog_api import CATEGORIES_URL, Json, ok
from tests.integration.modules.orders.test_ordering_api import (
    BILLS_URL,
    CART_URL,
    LINES_URL,
    ORDERS_URL,
    add,
    cart,
    menu_items,
    staff_of,
    submit,
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

QR_URL = "/api/v1/auth/qr"
REFRESH_URL = "/api/v1/auth/refresh"
NOT_OPEN = {
    "type": "about:blank",
    "title": "Conflict",
    "status": 409,
    "detail": "This table is not open yet; ask your waiter",
}


def scan(client: TestClient, qr_token: str, name: str | None = None) -> Response:
    body: dict[str, Any] = {"token": qr_token}
    if name is not None:
        body["name"] = name
    return client.post(QR_URL, json=body)


def guest_of(new_client: ClientFactory, qr_token: str, name: str | None = None) -> TestClient:
    client = new_client()
    response = scan(client, qr_token, name)
    assert response.status_code == 200, response.text
    assert response.json() == {"expires_in": 900, "role": "guest"}
    return client


def open_table(staff: TestClient, table: dict[str, str]) -> str:
    return str(ok(staff.post(BILLS_URL, json={"table_id": table["id"]}))["id"])


def pay(staff: TestClient, bill_id: str) -> None:
    ok(staff.post(f"{BILLS_URL}/{bill_id}/payment", json={"method": "cash"}))


def locked_out(guest: TestClient, item_id: str) -> None:
    """Nothing the guest can do at the table anymore: read, add, change, send, refresh, or ask who they are."""
    assert guest.get(CART_URL).status_code == 401
    assert add(guest, item_id).status_code == 401
    assert guest.patch(f"{LINES_URL}/{uuid.uuid4()}", json={"quantity": 2}).status_code == 401
    assert submit(guest, 1).status_code == 401
    assert guest.get(ORDERS_URL).status_code == 401
    assert me(guest).status_code == 401
    assert guest.post(REFRESH_URL).status_code == 401
    # The refresh answer also cleared both cookies: the phone is signed out for good.
    assert guest.get(CART_URL).status_code == 401


def forget_access_revocations() -> None:
    """Plays a Redis outage or restart: the fast access-token floor is gone, only Postgres remains."""
    with Redis.from_url(get_settings().redis_url) as redis:
        redis.flushdb()


def move_guests_joined_at(by: timedelta) -> None:
    async def run() -> None:
        engine = create_engine(get_settings().database_url)
        async with create_session_factory(engine)() as session:
            await session.execute(update(GuestModel).values(joined_at=GuestModel.joined_at - by))
            await session.commit()
        await engine.dispose()

    asyncio.run(run())


# --- Joining -------------------------------------------------------------------------------------


def test_a_qr_lets_nobody_in_while_the_table_is_closed(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    phone = new_client()

    closed = scan(phone, table["qr_token"])

    assert (closed.status_code, closed.json()) == (409, NOT_OPEN)
    assert "set-cookie" not in closed.headers
    assert phone.get(CART_URL).status_code == 401
    unknown = scan(phone, "not-a-real-qr-token")
    assert (unknown.status_code, unknown.json()["detail"]) == (401, "This QR code is not valid")
    assert scan(phone, "").status_code == 422


def test_any_number_of_phones_join_and_build_one_order_with_the_tablet(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin, "Mesa 5"))
    tablet = tablet_of(new_client, table)
    waiter = staff_of(new_client, admin, "mesero", "waiter")
    open_table(waiter, table)

    ana = guest_of(new_client, table["qr_token"], "Ana")
    phones = [guest_of(new_client, table["qr_token"]) for _ in range(5)]

    assert ok(me(ana))["guest"]["name"] == "Ana"
    assert ok(me(ana))["table"] == {"id": table["id"], "name": "Mesa 5"}
    assert [ok(me(phone))["guest"]["name"] for phone in phones] == [f"Guest {n}" for n in range(2, 7)]

    ok(add(ana, items["pastor"], 2))
    ok(add(phones[0], items["suadero"]))
    ok(add(tablet, items["pastor"]))
    shared = cart(phones[4])
    assert [(line["name"], line["added_by"]) for line in shared["lines"]] == [
        ("Pastor", "Ana"),
        ("Suadero", "Guest 2"),
        ("Pastor", "Tablet"),
    ]
    assert cart(ana) == cart(tablet) == shared

    order = ok(submit(phones[2], shared["version"]), 201)

    assert (order["sent_by"], order["total_cents"]) == ("Guest 4", 10200)
    for everyone in (ana, *phones, tablet):
        assert ok(everyone.get(ORDERS_URL)) == [order]
        assert cart(everyone)["lines"] == []


# --- Leaving: "nadie pueda acceder después de irse" ------------------------------------------------


def test_after_paying_nobody_who_left_can_order_even_with_the_app_still_open(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    waiter = staff_of(new_client, admin, "mesero", "waiter")
    bill_id = open_table(waiter, table)
    guests = [guest_of(new_client, table["qr_token"]) for _ in range(3)]
    ok(add(guests[0], items["pastor"]))
    ok(submit(guests[0], cart(guests[0])["version"]), 201)
    ok(add(guests[1], items["suadero"]))  # left in the cart when they pay

    pay(waiter, bill_id)

    for guest in guests:
        locked_out(guest, items["pastor"])
    # The same QR, scanned again from the street or from home, does not open a closed table.
    assert scan(new_client(), table["qr_token"]).json() == NOT_OPEN


def test_ending_the_visit_holds_even_if_redis_forgot_the_revocations(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    bill_id = open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    ok(add(guest, items["pastor"]))

    pay(admin, bill_id)
    forget_access_revocations()

    # The access token is still unexpired, but every table action re-checks the visit in Postgres.
    locked_out(guest, items["pastor"])


def test_old_guests_stay_out_when_the_table_opens_again_for_the_next_people(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    first_visit = open_table(admin, table)
    old_guest = guest_of(new_client, table["qr_token"])
    pay(admin, first_visit)
    forget_access_revocations()

    open_table(admin, table)  # the next customers sit down
    new_guest = guest_of(new_client, table["qr_token"])

    locked_out(old_guest, items["pastor"])
    ok(add(new_guest, items["pastor"]))
    assert ok(submit(new_guest, cart(new_guest)["version"]), 201)["sent_by"] == "Guest 1"


def test_a_visit_ends_after_twelve_hours_even_if_nobody_closes_the_table(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    refreshed = guest.post(REFRESH_URL)
    assert refreshed.status_code == 200
    # However often it refreshes, the session never outlives the visit limit.
    max_ages = [
        int(part.split("=")[1])
        for header in refreshed.headers.get_list("set-cookie")
        for part in header.split("; ")
        if part.startswith("Max-Age=")
    ]
    assert max(max_ages) <= int(timedelta(hours=12).total_seconds())

    move_guests_joined_at(timedelta(hours=12, minutes=1))  # "días después de haberse ido"

    locked_out(guest, items["pastor"])


def test_a_new_qr_signs_out_its_guests_and_the_old_one_stops_working(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])

    renewed = ok(admin.post(f"{TABLES_URL}/{table['id']}/qr"))

    assert renewed["qr_token"] != table["qr_token"]
    locked_out(guest, items["pastor"])
    assert scan(new_client(), table["qr_token"]).status_code == 401
    guest_of(new_client, renewed["qr_token"])  # the table is still open: the new QR works
    ok(add(tablet, items["pastor"]))  # the tablet is not signed out by a new QR


def test_deactivating_the_table_signs_out_its_guests(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])

    ok(admin.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False}))

    locked_out(guest, items["pastor"])
    assert scan(new_client(), table["qr_token"]).status_code == 401


def test_closing_a_table_without_orders_also_ends_its_guests(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    bill_id = open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])

    assert admin.post(f"{BILLS_URL}/{bill_id}/close").status_code == 204

    locked_out(guest, items["pastor"])


# --- What a guest can never do ---------------------------------------------------------------------


def test_a_guest_can_do_nothing_of_admin_waiter_or_kitchen(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    bill_id = open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])

    assert guest.get(TABLES_URL).status_code == 403
    assert guest.post(f"{TABLES_URL}/{table['id']}/qr").status_code == 403
    assert guest.post(CATEGORIES_URL, json={"name": "Hack"}).status_code == 403
    assert guest.get("/api/v1/staff").status_code == 403
    assert guest.get(f"{BILLS_URL}/tables").status_code == 403
    assert guest.post(BILLS_URL, json={"table_id": table["id"]}).status_code == 403
    assert guest.post(f"{BILLS_URL}/{bill_id}/payment", json={"method": "cash"}).status_code == 403
    assert guest.post(f"{BILLS_URL}/{bill_id}/close").status_code == 403
    assert guest.get("/api/v1/menu").status_code == 200


def test_a_guest_never_reaches_another_table_or_tenant(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    mesa_4, mesa_5 = created(create_table(admin, "Mesa 4")), created(create_table(admin, "Mesa 5"))
    open_table(admin, mesa_4)
    open_table(admin, mesa_5)
    at_4 = guest_of(new_client, mesa_4["qr_token"])
    at_5 = guest_of(new_client, mesa_5["qr_token"])
    line = ok(add(at_4, items["pastor"]))["lines"][0]
    ok(submit(at_4, cart(at_4)["version"]), 201)
    line = ok(add(at_4, items["pastor"]))["lines"][0]
    other_admin = admin_of(new_client, "boss@example.com")
    other_table = created(create_table(other_admin))
    open_table(other_admin, other_table)
    other_tenant = guest_of(new_client, other_table["qr_token"])

    for intruder in (at_5, other_tenant):
        assert cart(intruder)["lines"] == []
        assert ok(intruder.get(ORDERS_URL)) == []
        assert intruder.patch(f"{LINES_URL}/{line['id']}", json={"quantity": 9}).status_code == 404
        assert intruder.delete(f"{LINES_URL}/{line['id']}").status_code == 404
    assert add(other_tenant, items["pastor"]).status_code == 409  # not on that tenant's menu
    assert cart(at_4)["lines"][0]["quantity"] == 1


def test_a_forged_guest_token_for_another_visit_or_table_is_refused(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    mesa_4, mesa_5 = created(create_table(admin, "Mesa 4")), created(create_table(admin, "Mesa 5"))
    open_table(admin, mesa_4)
    bill_5 = open_table(admin, mesa_5)
    guest = guest_of(new_client, mesa_4["qr_token"])
    guest_id = uuid.UUID(ok(me(guest))["guest"]["id"])
    forger = new_client()

    for claims in (
        # Even signed with the real key: the claims must match the guest's own visit.
        claims_for(guest_id, tenant_a.tenant_id, "guest", table_id=mesa_5["id"], bill_id=bill_5),
        claims_for(guest_id, tenant_a.tenant_id, "guest", table_id=mesa_4["id"], bill_id=bill_5),
        claims_for(guest_id, tenant_a.tenant_id, "guest", table_id=mesa_4["id"]),  # no visit at all
    ):
        headers = {"Cookie": f"access_token={sign(claims)}"}
        assert forger.get(CART_URL, headers=headers).status_code == 401
        assert forger.post(LINES_URL, json={"item_id": items["pastor"]}, headers=headers).status_code == 401
        assert forger.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_wrong_qrs_are_limited_but_scanning_a_closed_table_never_locks_anyone_out(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    phone = new_client()

    for _ in range(get_settings().login_max_failures_per_client + 3):
        assert scan(phone, table["qr_token"]).status_code == 409  # before the waiter opens the table
    open_table(admin, table)
    assert scan(phone, table["qr_token"]).status_code == 200

    guesser = new_client()
    for _ in range(get_settings().login_max_failures_per_client):
        assert scan(guesser, "guessed-token").status_code == 401
    assert scan(guesser, "guessed-token").status_code == 429
