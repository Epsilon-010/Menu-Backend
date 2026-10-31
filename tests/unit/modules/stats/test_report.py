"""Slice 16 S2-S6: the statistics are computed from raw sales records, with days in the business's zone."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.modules.stats.domain.errors import InvalidStatsRange
from app.modules.stats.domain.report import (
    BillState,
    PaidBill,
    SentDish,
    SentOrder,
    build_statistics,
    day_bounds,
    validate_range,
)

MEXICO = ZoneInfo("America/Mexico_City")  # UTC-6 all year (no daylight saving since 2022)
DAY = date(2026, 10, 20)
TACO, SODA = uuid.uuid4(), uuid.uuid4()
TABLE_1, TABLE_2 = uuid.uuid4(), uuid.uuid4()
NAMES = {TABLE_1: "Mesa 1", TABLE_2: "Mesa 2"}


def local(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A moment given in Mexico City time, stored as UTC like the database does."""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=MEXICO).astimezone(UTC)


def dish(
    item_id: uuid.UUID = TACO,
    name: str = "Taco",
    quantity: int = 1,
    subtotal_cents: int = 3000,
    cancelled: bool = False,
    **times: datetime | None,
) -> SentDish:
    return SentDish(
        item_id=item_id,
        name=name,
        quantity=quantity,
        subtotal_cents=subtotal_cents,
        cancelled=cancelled,
        queued_at=times.get("queued_at") or local(DAY, 12),
        preparing_at=times.get("preparing_at"),
        ready_at=times.get("ready_at"),
        delivered_at=times.get("delivered_at"),
    )


def order(*dishes: SentDish, sent_at: datetime | None = None, state: BillState = BillState.PAID, table=TABLE_1) -> SentOrder:  # type: ignore[no-untyped-def]
    return SentOrder(table_id=table, sent_at=sent_at or local(DAY, 12), bill_state=state, dishes=tuple(dishes))


def stats(bills: list[PaidBill] = [], orders: list[SentOrder] = [], first: date = DAY, last: date = DAY):  # type: ignore[no-untyped-def]  # noqa: B006
    return build_statistics(first, last, MEXICO, bills, orders, NAMES)


# --- Range (S2) ------------------------------------------------------------------------------------


def test_the_range_covers_whole_local_days() -> None:
    start, end = day_bounds(date(2026, 10, 20), date(2026, 10, 21), MEXICO)

    assert start == datetime(2026, 10, 20, 6, tzinfo=UTC)
    assert end == datetime(2026, 10, 22, 6, tzinfo=UTC)


def test_a_day_with_a_clock_change_is_still_one_local_day() -> None:
    madrid = ZoneInfo("Europe/Madrid")  # clocks went back on 2026-10-25: that day lasts 25 hours

    start, end = day_bounds(date(2026, 10, 25), date(2026, 10, 25), madrid)

    assert end - start == timedelta(hours=25)


def test_the_end_cannot_be_before_the_start() -> None:
    with pytest.raises(InvalidStatsRange, match="The end date must be on or after the start date"):
        validate_range(date(2026, 10, 2), date(2026, 10, 1))


def test_the_range_is_at_most_366_days() -> None:
    validate_range(date(2026, 1, 1), date(2027, 1, 1))  # 366 days

    with pytest.raises(InvalidStatsRange, match="The range can be at most 366 days"):
        validate_range(date(2026, 1, 1), date(2027, 1, 2))


# --- Sales (S3) ------------------------------------------------------------------------------------


def test_collected_and_pending_are_separate_and_every_day_is_listed() -> None:
    second = DAY + timedelta(days=1)
    result = stats(
        bills=[
            PaidBill(paid_at=local(DAY, 13), method="cash", amount_cents=10000),
            PaidBill(paid_at=local(DAY, 23, 59), method="card", amount_cents=5000),
        ],
        orders=[
            order(dish(subtotal_cents=4000), dish(subtotal_cents=999, cancelled=True), sent_at=local(second, 9), state=BillState.OPEN),
            order(dish(subtotal_cents=7000), state=BillState.PAID),
        ],
        last=DAY + timedelta(days=2),
    )

    assert result.totals.collected_cents == 15000
    assert result.totals.paid_bills == 2
    assert result.totals.average_ticket_cents == 7500
    assert result.totals.pending_cents == 4000
    assert result.totals.pending_orders == 1
    assert [(d.date, d.collected_cents, d.pending_cents) for d in result.days] == [
        (DAY, 15000, 0),
        (second, 0, 4000),
        (DAY + timedelta(days=2), 0, 0),
    ]


def test_a_payment_after_local_midnight_belongs_to_the_next_day() -> None:
    # 00:30 in Mexico City is 06:30 UTC: the same UTC date as the day before's afternoon, another local day.
    result = stats(
        bills=[PaidBill(paid_at=local(DAY + timedelta(days=1), 0, 30), method="cash", amount_cents=100)],
        last=DAY + timedelta(days=1),
    )

    assert [d.collected_cents for d in result.days] == [0, 100]


def test_no_sales_gives_zeros_not_errors() -> None:
    result = stats()

    assert result.totals.average_ticket_cents == 0
    assert result.totals.collected_cents == result.totals.pending_cents == 0
    assert [(m.method, m.bills, m.amount_cents) for m in result.payment_methods] == [
        ("cash", 0, 0),
        ("card", 0, 0),
        ("other", 0, 0),
    ]


def test_sales_by_payment_method() -> None:
    result = stats(
        bills=[
            PaidBill(paid_at=local(DAY, 13), method="card", amount_cents=200),
            PaidBill(paid_at=local(DAY, 14), method="card", amount_cents=300),
            PaidBill(paid_at=local(DAY, 15), method="other", amount_cents=50),
        ]
    )

    assert [(m.method, m.bills, m.amount_cents) for m in result.payment_methods] == [
        ("cash", 0, 0),
        ("card", 2, 500),
        ("other", 1, 50),
    ]


def test_the_average_ticket_rounds_to_the_nearest_cent() -> None:
    bills = [PaidBill(paid_at=local(DAY, 13), method="cash", amount_cents=c) for c in (100, 100, 101)]

    assert stats(bills=bills).totals.average_ticket_cents == 100


def test_a_fully_cancelled_order_is_not_pending() -> None:
    result = stats(orders=[order(dish(cancelled=True), state=BillState.OPEN)])

    assert result.totals.pending_orders == 0
    assert result.totals.pending_cents == 0


# --- Products and tables (S4, S5) ------------------------------------------------------------------


def test_products_add_up_quantity_and_split_collected_from_pending() -> None:
    result = stats(
        orders=[
            order(dish(quantity=2, subtotal_cents=6000), dish(SODA, "Soda", 1, 2000), state=BillState.PAID),
            order(dish(quantity=1, subtotal_cents=3000, name="Taco al pastor"), sent_at=local(DAY, 14), state=BillState.OPEN),
            order(dish(SODA, "Soda", 5, 10000, cancelled=True), state=BillState.OPEN),
        ]
    )

    assert [(p.item_id, p.name, p.quantity, p.collected_cents, p.pending_cents) for p in result.products] == [
        (TACO, "Taco al pastor", 3, 6000, 3000),
        (SODA, "Soda", 1, 2000, 0),
    ]


def test_products_with_the_same_quantity_go_by_amount() -> None:
    result = stats(orders=[order(dish(SODA, "Soda", 1, 2000), dish(TACO, "Taco", 1, 3000))])

    assert [p.name for p in result.products] == ["Taco", "Soda"]


def test_a_bill_closed_without_payment_is_neither_collected_nor_pending() -> None:
    result = stats(orders=[order(dish(), state=BillState.CLOSED)])

    assert result.products == []
    assert result.tables == []
    assert result.totals.pending_cents == 0


def test_orders_by_table() -> None:
    result = stats(
        orders=[
            order(dish(subtotal_cents=100), table=TABLE_2, state=BillState.PAID),
            order(dish(subtotal_cents=200), table=TABLE_2, state=BillState.OPEN),
            order(dish(subtotal_cents=400), table=TABLE_1, state=BillState.PAID),
            order(dish(cancelled=True), table=TABLE_1, state=BillState.PAID),
        ]
    )

    assert [(t.table_id, t.name, t.orders, t.collected_cents, t.pending_cents) for t in result.tables] == [
        (TABLE_2, "Mesa 2", 2, 100, 200),
        (TABLE_1, "Mesa 1", 1, 400, 0),
    ]


# --- Times (S6) ------------------------------------------------------------------------------------


def timed(queue: int, preparation: int, delivery: int, start: datetime | None = None, **extra) -> SentDish:  # type: ignore[no-untyped-def]
    """A dish that waited `queue` s, took `preparation` s and waited `delivery` s to be delivered."""
    queued = start or local(DAY, 12)
    preparing = queued + timedelta(seconds=queue)
    ready = preparing + timedelta(seconds=preparation)
    return dish(
        queued_at=queued,
        preparing_at=preparing,
        ready_at=ready,
        delivered_at=ready + timedelta(seconds=delivery),
        **extra,
    )


def test_each_stage_has_an_average_and_a_median() -> None:
    result = stats(orders=[order(timed(60, 300, 30)), order(timed(120, 600, 60)), order(timed(900, 1200, 90))])

    queue = result.times.queue
    assert (queue.average_seconds, queue.median_seconds, queue.count) == (360, 120, 3)
    assert (result.times.preparation.average_seconds, result.times.preparation.median_seconds) == (700, 600)
    assert (result.times.delivery.average_seconds, result.times.delivery.median_seconds) == (60, 60)


def test_a_dish_counts_only_in_the_stages_it_finished() -> None:
    preparing_now = dish(queued_at=local(DAY, 12), preparing_at=local(DAY, 12, 2))

    result = stats(orders=[order(preparing_now, state=BillState.OPEN)])

    assert (result.times.queue.median_seconds, result.times.queue.count) == (120, 1)
    assert result.times.preparation.count == 0
    assert result.times.preparation.average_seconds is None
    assert result.times.preparation.median_seconds is None


def test_a_dish_with_no_preparation_waits_in_the_queue_until_it_is_ready() -> None:
    drink = dish(queued_at=local(DAY, 12), ready_at=local(DAY, 12, 3), delivered_at=local(DAY, 12, 4))

    result = stats(orders=[order(drink)])

    assert (result.times.queue.median_seconds, result.times.queue.count) == (180, 1)
    assert result.times.preparation.count == 0
    assert result.times.delivery.median_seconds == 60


def test_cancelled_dishes_never_count_in_times() -> None:
    result = stats(orders=[order(timed(60, 60, 60, cancelled=True))])

    assert result.times.queue.count == 0


def test_a_dish_added_later_waits_from_when_it_was_added() -> None:
    late = timed(30, 60, 10, start=local(DAY, 12, 40))

    result = stats(orders=[order(late, sent_at=local(DAY, 12))])

    assert result.times.queue.median_seconds == 30


def test_the_order_time_runs_until_its_last_live_dish_is_delivered() -> None:
    sent = local(DAY, 12)
    complete = order(timed(60, 60, 60, start=sent), timed(60, 600, 60, start=sent), dish(cancelled=True), sent_at=sent)
    unfinished = order(timed(60, 60, 60, start=sent), dish(queued_at=sent), sent_at=sent)

    result = stats(orders=[complete, unfinished])

    assert (result.times.order.median_seconds, result.times.order.count) == (720, 1)


def test_times_per_product() -> None:
    result = stats(orders=[order(timed(60, 300, 30), timed(120, 100, 10, item_id=SODA, name="Soda"), timed(180, 500, 50))])

    by_name = {p.name: p for p in result.times.products}
    assert (by_name["Taco"].queue.median_seconds, by_name["Taco"].preparation.average_seconds) == (120, 400)
    assert (by_name["Soda"].queue.count, by_name["Soda"].delivery.median_seconds) == (1, 10)
    assert [p.name for p in result.times.products] == ["Taco", "Soda"]
