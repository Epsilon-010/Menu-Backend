"""Raw sales records the orders module hands out for reports (the stats module)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

BillOutcome = Literal["open", "paid", "closed"]


@dataclass(frozen=True)
class ReportedBill:
    paid_at: datetime
    payment_method: str
    paid_cents: int


@dataclass(frozen=True)
class ReportedDish:
    item_id: uuid.UUID
    name: str
    quantity: int
    unit_price_cents: int
    status: str
    queued_at: datetime
    # From the dish's status history; each status is reached at most once.
    preparing_at: datetime | None
    ready_at: datetime | None
    delivered_at: datetime | None


@dataclass(frozen=True)
class ReportedOrder:
    table_id: uuid.UUID
    sent_at: datetime
    bill: BillOutcome
    dishes: tuple[ReportedDish, ...]


class SalesReports(Protocol):
    """`start` inclusive, `end` exclusive."""

    async def paid_bills(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[ReportedBill]:
        """Bills paid in the window, by payment time."""
        ...

    async def sent_orders(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[ReportedOrder]:
        """Orders sent in the window, with each dish's status history condensed."""
        ...
