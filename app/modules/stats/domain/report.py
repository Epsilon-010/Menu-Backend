"""Statistics of a business for a range of days, computed from raw sales records.

Days are calendar days in the business's time zone. Two kinds of sales are never mixed: what was
collected (paid bills, dated by the payment) and what was ordered but not collected yet (dishes of open
bills, dated by when the order was sent).
"""

import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.modules.stats.domain.errors import InvalidStatsRange

MAX_RANGE_DAYS = 366
PAYMENT_METHODS = ("cash", "card", "other")


class BillState(StrEnum):
    OPEN = "open"
    PAID = "paid"
    # Closed by staff without a payment: nothing was sold.
    CLOSED = "closed"


@dataclass(frozen=True)
class PaidBill:
    paid_at: datetime
    method: str
    amount_cents: int


@dataclass(frozen=True)
class SentDish:
    item_id: uuid.UUID
    name: str
    quantity: int
    subtotal_cents: int
    cancelled: bool
    # When it entered the kitchen queue: the order's send time, or when staff added it later.
    queued_at: datetime
    preparing_at: datetime | None
    ready_at: datetime | None
    delivered_at: datetime | None


@dataclass(frozen=True)
class SentOrder:
    table_id: uuid.UUID
    sent_at: datetime
    bill_state: BillState
    dishes: tuple[SentDish, ...]

    @property
    def live_dishes(self) -> tuple[SentDish, ...]:
        return tuple(dish for dish in self.dishes if not dish.cancelled)

    @property
    def amount_cents(self) -> int:
        return sum(dish.subtotal_cents for dish in self.live_dishes)


@dataclass(frozen=True)
class Totals:
    collected_cents: int
    paid_bills: int
    average_ticket_cents: int
    pending_cents: int
    pending_orders: int


@dataclass(frozen=True)
class DaySales:
    date: date
    collected_cents: int
    pending_cents: int


@dataclass(frozen=True)
class MethodSales:
    method: str
    bills: int
    amount_cents: int


@dataclass(frozen=True)
class ProductSales:
    item_id: uuid.UUID
    name: str
    quantity: int
    collected_cents: int
    pending_cents: int


@dataclass(frozen=True)
class TableSales:
    table_id: uuid.UUID
    name: str
    orders: int
    collected_cents: int
    pending_cents: int


@dataclass(frozen=True)
class Duration:
    """Seconds; average and median are None when nothing finished the stage."""

    average_seconds: int | None
    median_seconds: int | None
    count: int


@dataclass(frozen=True)
class ProductTimes:
    item_id: uuid.UUID
    name: str
    queue: Duration
    preparation: Duration
    delivery: Duration


@dataclass(frozen=True)
class Times:
    queue: Duration
    preparation: Duration
    delivery: Duration
    order: Duration
    products: list[ProductTimes]


@dataclass(frozen=True)
class Statistics:
    first_day: date
    last_day: date
    timezone: str
    totals: Totals
    days: list[DaySales]
    payment_methods: list[MethodSales]
    products: list[ProductSales]
    tables: list[TableSales]
    times: Times


def validate_range(first_day: date, last_day: date) -> None:
    if last_day < first_day:
        raise InvalidStatsRange("The end date must be on or after the start date")
    if (last_day - first_day).days + 1 > MAX_RANGE_DAYS:
        raise InvalidStatsRange(f"The range can be at most {MAX_RANGE_DAYS} days")


def day_bounds(first_day: date, last_day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Where the range starts and ends (exclusive): local midnights, whatever the clock changes."""
    start = datetime.combine(first_day, time(), tzinfo=zone)
    end = datetime.combine(last_day + timedelta(days=1), time(), tzinfo=zone)
    # In UTC: subtracting two datetimes of the same zone would ignore a clock change between them.
    return start.astimezone(UTC), end.astimezone(UTC)


def build_statistics(
    first_day: date,
    last_day: date,
    zone: ZoneInfo,
    bills: Iterable[PaidBill],
    orders: Iterable[SentOrder],
    table_names: Mapping[uuid.UUID, str],
) -> Statistics:
    paid = list(bills)
    sent = sorted(orders, key=lambda order: order.sent_at)
    sold = [order for order in sent if order.bill_state is not BillState.CLOSED and order.live_dishes]
    pending = [order for order in sold if order.bill_state is BillState.OPEN]
    collected_cents = sum(bill.amount_cents for bill in paid)
    totals = Totals(
        collected_cents=collected_cents,
        paid_bills=len(paid),
        average_ticket_cents=round(collected_cents / len(paid)) if paid else 0,
        pending_cents=sum(order.amount_cents for order in pending),
        pending_orders=len(pending),
    )
    return Statistics(
        first_day=first_day,
        last_day=last_day,
        timezone=zone.key,
        totals=totals,
        days=_days(first_day, last_day, zone, paid, pending),
        payment_methods=_payment_methods(paid),
        products=_products(sold),
        tables=_tables(sold, table_names),
        times=_times(sent),
    )


def _days(
    first_day: date, last_day: date, zone: ZoneInfo, bills: list[PaidBill], pending: list[SentOrder]
) -> list[DaySales]:
    collected: dict[date, int] = defaultdict(int)
    ordered: dict[date, int] = defaultdict(int)
    for bill in bills:
        collected[bill.paid_at.astimezone(zone).date()] += bill.amount_cents
    for order in pending:
        ordered[order.sent_at.astimezone(zone).date()] += order.amount_cents
    days = (first_day + timedelta(days=n) for n in range((last_day - first_day).days + 1))
    return [DaySales(date=day, collected_cents=collected[day], pending_cents=ordered[day]) for day in days]


def _payment_methods(bills: list[PaidBill]) -> list[MethodSales]:
    return [
        MethodSales(
            method=method,
            bills=sum(1 for bill in bills if bill.method == method),
            amount_cents=sum(bill.amount_cents for bill in bills if bill.method == method),
        )
        for method in PAYMENT_METHODS
    ]


def _split(order: SentOrder, cents: int) -> tuple[int, int]:
    """(collected, pending) for an amount of an order that was sold."""
    return (cents, 0) if order.bill_state is BillState.PAID else (0, cents)


def _products(orders: list[SentOrder]) -> list[ProductSales]:
    names: dict[uuid.UUID, str] = {}
    quantity: dict[uuid.UUID, int] = defaultdict(int)
    collected: dict[uuid.UUID, int] = defaultdict(int)
    pending: dict[uuid.UUID, int] = defaultdict(int)
    for order in orders:  # oldest first, so the latest name ordered wins
        for dish in order.live_dishes:
            names[dish.item_id] = dish.name
            quantity[dish.item_id] += dish.quantity
            paid, unpaid = _split(order, dish.subtotal_cents)
            collected[dish.item_id] += paid
            pending[dish.item_id] += unpaid
    products = [
        ProductSales(item_id, names[item_id], quantity[item_id], collected[item_id], pending[item_id])
        for item_id in names
    ]
    return sorted(products, key=lambda p: (-p.quantity, -(p.collected_cents + p.pending_cents), p.name))


def _tables(orders: list[SentOrder], table_names: Mapping[uuid.UUID, str]) -> list[TableSales]:
    count: dict[uuid.UUID, int] = defaultdict(int)
    collected: dict[uuid.UUID, int] = defaultdict(int)
    pending: dict[uuid.UUID, int] = defaultdict(int)
    for order in orders:
        count[order.table_id] += 1
        paid, unpaid = _split(order, order.amount_cents)
        collected[order.table_id] += paid
        pending[order.table_id] += unpaid
    tables = [
        TableSales(table_id, table_names.get(table_id, ""), count[table_id], collected[table_id], pending[table_id])
        for table_id in count
    ]
    return sorted(tables, key=lambda t: (-t.orders, -(t.collected_cents + t.pending_cents), t.name))


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds()


def _duration(samples: Sequence[float | None]) -> Duration:
    values = [value for value in samples if value is not None]
    if not values:
        return Duration(average_seconds=None, median_seconds=None, count=0)
    return Duration(
        average_seconds=round(statistics.fmean(values)),
        median_seconds=round(statistics.median(values)),
        count=len(values),
    )


def _queue(dish: SentDish) -> float | None:
    """Until the kitchen started it, or until it was ready when it needed no preparation (a drink)."""
    return _seconds(dish.queued_at, dish.preparing_at or dish.ready_at)


def _preparation(dish: SentDish) -> float | None:
    return _seconds(dish.preparing_at, dish.ready_at)


def _delivery(dish: SentDish) -> float | None:
    return _seconds(dish.ready_at, dish.delivered_at)


def _order_time(order: SentOrder) -> float | None:
    """Only completed orders: sent until their last live dish was delivered."""
    delivered = [dish.delivered_at for dish in order.live_dishes]
    if not delivered or any(at is None for at in delivered):
        return None
    return _seconds(order.sent_at, max(at for at in delivered if at is not None))


def _times(orders: list[SentOrder]) -> Times:
    dishes = [dish for order in orders for dish in order.live_dishes]
    by_product: dict[uuid.UUID, list[SentDish]] = defaultdict(list)
    for dish in dishes:
        by_product[dish.item_id].append(dish)
    products = [
        ProductTimes(
            item_id=item_id,
            name=group[-1].name,
            queue=_duration([_queue(dish) for dish in group]),
            preparation=_duration([_preparation(dish) for dish in group]),
            delivery=_duration([_delivery(dish) for dish in group]),
        )
        for item_id, group in by_product.items()
    ]
    return Times(
        queue=_duration([_queue(dish) for dish in dishes]),
        preparation=_duration([_preparation(dish) for dish in dishes]),
        delivery=_duration([_delivery(dish) for dish in dishes]),
        order=_duration([_order_time(order) for order in orders]),
        products=sorted(products, key=lambda p: (-len(by_product[p.item_id]), p.name)),
    )
