"""Slice 16 S2-S6, S8: the admin's statistics from real orders, bills and dish histories."""

import asyncio
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine
from tests.integration.modules.catalog.test_catalog_api import Json, ok
from tests.integration.modules.orders.test_kitchen_api import mark, send_order
from tests.integration.modules.orders.test_ordering_api import BILLS_URL, menu_items, staff_of, tables_overview
from tests.integration.modules.orders.test_paid_bills_api import add_dish
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

STATS_URL = "/api/v1/stats"
SETTINGS_URL = "/api/v1/tenant/settings"
DAY = "2026-10-20"
T0 = "2026-10-20T12:00:00-06:00"  # noon in Mexico City


def run_sql(*statements: tuple[str, dict[str, Any]]) -> list[Any]:
    async def go() -> list[Any]:
        engine = create_engine(get_settings().database_url)
        results = []
        async with engine.begin() as conn:
            for sql, params in statements:
                result = await conn.execute(text(sql), params)
                results.append(result.all() if result.returns_rows else None)
        await engine.dispose()
        return results

    return asyncio.run(go())


def at(moment: str, seconds: int = 0) -> datetime:
    return datetime.fromisoformat(moment) + timedelta(seconds=seconds)


def stats(client: TestClient, first: str = DAY, last: str = DAY) -> Json:
    return ok(client.get(STATS_URL, params={"from": first, "to": last}))


class Business:
    """An admin, a tablet at "Mesa 1", a cook and a waiter of tenant A, with two items to order."""

    def __init__(self, new_client: ClientFactory) -> None:
        self.admin = admin_of(new_client)
        self.items = menu_items(self.admin)  # pastor 2500, suadero 2700
        self.table = created(create_table(self.admin, "Mesa 1"))
        self.tablet = tablet_of(new_client, self.table)
        self.cook = staff_of(new_client, self.admin, "cook.stats", "kitchen")
        self.waiter = staff_of(new_client, self.admin, "waiter.stats", "waiter")

    def bill_id(self) -> str:
        return str(tables_overview(self.waiter)[0]["bill"]["id"])


@pytest.fixture
def business(new_client: ClientFactory, tenant_a: SeedResult) -> Business:
    return Business(new_client)


def serve_and_pay(business: Business) -> Json:
    """One order of two pastor dishes, cooked, delivered and paid by card, moved to fixed times on DAY."""
    order = send_order(business.tablet, business.items["pastor"], 2)
    dishes = order["items"]
    ok(mark(business.cook, order, dishes, "preparing"))
    ok(mark(business.cook, order, dishes, "ready"))
    ok(mark(business.waiter, order, dishes, "delivered"))
    bill_id = business.bill_id()
    ok(business.waiter.post(f"{BILLS_URL}/{bill_id}/payment", json={"method": "card"}))

    first, second = dishes[0]["id"], dishes[1]["id"]
    change = "UPDATE order_item_changes SET changed_at = :at WHERE order_item_id = :id AND to_status = :status"
    run_sql(
        ("UPDATE orders SET created_at = :at WHERE id = :id", {"at": at(T0), "id": order["id"]}),
        ("UPDATE order_items SET queued_at = :at WHERE order_id = :id", {"at": at(T0), "id": order["id"]}),
        (change, {"at": at(T0, 60), "id": first, "status": "preparing"}),
        (change, {"at": at(T0, 180), "id": second, "status": "preparing"}),
        (change, {"at": at(T0, 360), "id": first, "status": "ready"}),
        (change, {"at": at(T0, 480), "id": second, "status": "ready"}),
        (change, {"at": at(T0, 390), "id": first, "status": "delivered"}),
        (change, {"at": at(T0, 540), "id": second, "status": "delivered"}),
        ("UPDATE bills SET closed_at = :at WHERE id = :id", {"at": at(T0, 3600), "id": bill_id}),
    )
    return {"order": order, "bill_id": bill_id}


# --- Done when: sales, products, tables, methods and times of a served and paid order ----------------


def test_a_served_and_paid_order_shows_in_every_figure(business: Business) -> None:
    served = serve_and_pay(business)

    result = stats(business.admin)

    assert (result["from"], result["to"], result["timezone"]) == (DAY, DAY, "America/Mexico_City")
    assert result["totals"] == {
        "collected_cents": 5000,
        "paid_bills": 1,
        "average_ticket_cents": 5000,
        "pending_cents": 0,
        "pending_orders": 0,
    }
    assert result["days"] == [{"date": DAY, "collected_cents": 5000, "pending_cents": 0}]
    assert result["payment_methods"] == [
        {"method": "cash", "bills": 0, "amount_cents": 0},
        {"method": "card", "bills": 1, "amount_cents": 5000},
        {"method": "other", "bills": 0, "amount_cents": 0},
    ]
    assert result["products"] == [
        {"item_id": business.items["pastor"], "name": "Pastor", "quantity": 2, "collected_cents": 5000, "pending_cents": 0}
    ]
    assert result["tables"] == [
        {"table_id": business.table["id"], "name": "Mesa 1", "orders": 1, "collected_cents": 5000, "pending_cents": 0}
    ]
    times = result["times"]
    assert times["queue"] == {"average_seconds": 120, "median_seconds": 120, "count": 2}
    assert times["preparation"] == {"average_seconds": 300, "median_seconds": 300, "count": 2}
    assert times["delivery"] == {"average_seconds": 45, "median_seconds": 45, "count": 2}
    assert times["order"] == {"average_seconds": 540, "median_seconds": 540, "count": 1}
    assert [(p["name"], p["queue"]["count"]) for p in times["products"]] == [("Pastor", 2)]
    assert served["order"]["id"]


@pytest.mark.parametrize(("first", "last"), [("2026-10-21", "2026-10-22"), ("2026-10-19", "2026-10-19")])
def test_days_outside_the_range_show_nothing(business: Business, first: str, last: str) -> None:
    serve_and_pay(business)

    result = stats(business.admin, first, last)

    assert result["totals"]["collected_cents"] == 0
    assert result["products"] == [] and result["tables"] == []
    assert result["times"]["queue"]["count"] == 0
    assert [day["date"] for day in result["days"]][0] == first


def test_days_are_cut_in_the_business_time_zone(business: Business) -> None:
    served = serve_and_pay(business)
    # 23:30 on the 20th in Mexico City is 05:30 on the 21st in UTC.
    run_sql(("UPDATE bills SET closed_at = :at WHERE id = :id", {"at": at("2026-10-21T05:30:00+00:00"), "id": served["bill_id"]}))

    in_mexico = stats(business.admin, "2026-10-20", "2026-10-21")["days"]
    ok(business.admin.patch(SETTINGS_URL, json={"timezone": "UTC"}))
    in_utc = stats(business.admin, "2026-10-20", "2026-10-21")["days"]

    assert [day["collected_cents"] for day in in_mexico] == [5000, 0]
    assert [day["collected_cents"] for day in in_utc] == [0, 5000]


def test_an_open_bill_is_pending_without_cancelled_dishes_and_with_dishes_added_later(business: Business) -> None:
    order = send_order(business.tablet, business.items["pastor"], 2)
    ok(mark(business.cook, order, order["items"][:1], "cancelled", reason="No pineapple"))
    ok(add_dish(business.waiter, order, business.items["suadero"]), 201)
    today = datetime.now(ZoneInfo("America/Mexico_City")).date().isoformat()

    result = stats(business.admin, today, today)

    assert (result["totals"]["pending_cents"], result["totals"]["pending_orders"]) == (5200, 1)
    assert result["totals"]["collected_cents"] == 0
    assert result["days"] == [{"date": today, "collected_cents": 0, "pending_cents": 5200}]
    assert [(p["name"], p["quantity"], p["collected_cents"], p["pending_cents"]) for p in result["products"]] == [
        ("Suadero", 1, 0, 2700),
        ("Pastor", 1, 0, 2500),
    ]
    assert result["tables"][0]["pending_cents"] == 5200
    [[(order_sent, added_queued)]] = run_sql(
        (
            "SELECT o.created_at, i.queued_at FROM order_items i JOIN orders o ON o.id = i.order_id "
            "WHERE i.order_id = :id AND i.name = 'Suadero'",
            {"id": order["id"]},
        )
    )
    assert added_queued > order_sent


# --- Range validation (S2) -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"from": "2026-10-21", "to": "2026-10-20"}, "The end date must be on or after the start date"),
        ({"from": "2026-01-01", "to": "2027-01-02"}, "The range can be at most 366 days"),
    ],
)
def test_an_invalid_range_is_422(business: Business, params: dict[str, str], detail: str) -> None:
    refused = business.admin.get(STATS_URL, params=params)

    assert refused.status_code == 422
    assert refused.json()["detail"] == detail


@pytest.mark.parametrize("params", [{}, {"from": DAY}, {"from": "20-10-2026", "to": DAY}, {"from": DAY, "to": "x"}])
def test_missing_or_malformed_dates_are_422(business: Business, params: dict[str, str]) -> None:
    assert business.admin.get(STATS_URL, params=params).status_code == 422


# --- Isolation (S8) --------------------------------------------------------------------------------


def test_only_the_admin_sees_the_statistics(business: Business, new_client: ClientFactory) -> None:
    for other in (business.waiter, business.cook, business.tablet):
        assert other.get(STATS_URL, params={"from": DAY, "to": DAY}).status_code == 403
    assert new_client().get(STATS_URL, params={"from": DAY, "to": DAY}).status_code == 401


def test_another_business_never_sees_these_figures(
    business: Business, new_client: ClientFactory, tenant_b: SeedResult
) -> None:
    serve_and_pay(business)

    other = stats(admin_of(new_client, "boss@example.com"))

    assert other["totals"]["collected_cents"] == 0
    assert other["products"] == [] and other["tables"] == []
    assert other["times"]["order"]["count"] == 0
