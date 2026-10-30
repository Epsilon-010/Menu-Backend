import uuid
from datetime import UTC, date, datetime

import pytest

from app.modules.stats.application.get_statistics import GetStatistics
from app.modules.stats.domain.errors import InvalidStatsRange
from app.modules.stats.domain.report import PaidBill, SentOrder

pytestmark = pytest.mark.anyio

MINE, OTHER = uuid.uuid4(), uuid.uuid4()


class FakeSales:
    """Records per tenant; remembers the windows it was asked for."""

    def __init__(self) -> None:
        self.zones = {MINE: "America/Mexico_City", OTHER: "Asia/Tokyo"}
        self.bills: dict[uuid.UUID, list[PaidBill]] = {MINE: [], OTHER: []}
        self.windows: list[tuple[uuid.UUID, datetime, datetime]] = []

    async def timezone(self, tenant_id: uuid.UUID) -> str:
        return self.zones[tenant_id]

    async def paid_bills(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[PaidBill]:
        self.windows.append((tenant_id, start, end))
        return [bill for bill in self.bills[tenant_id] if start <= bill.paid_at < end]

    async def sent_orders(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[SentOrder]:
        return []

    async def table_names(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, str]:
        return {}


async def test_reads_the_records_of_the_tenant_for_its_local_days() -> None:
    sales = FakeSales()
    sales.bills[MINE].append(PaidBill(datetime(2026, 10, 20, 7, tzinfo=UTC), "cash", 500))
    sales.bills[OTHER].append(PaidBill(datetime(2026, 10, 20, 7, tzinfo=UTC), "cash", 999))

    result = await GetStatistics(sales).execute(MINE, date(2026, 10, 20), date(2026, 10, 20))

    assert result.timezone == "America/Mexico_City"
    assert result.totals.collected_cents == 500
    assert sales.windows == [
        (MINE, datetime(2026, 10, 20, 6, tzinfo=UTC), datetime(2026, 10, 21, 6, tzinfo=UTC))
    ]


async def test_an_invalid_range_reads_nothing() -> None:
    sales = FakeSales()

    with pytest.raises(InvalidStatsRange):
        await GetStatistics(sales).execute(MINE, date(2026, 10, 21), date(2026, 10, 20))

    assert sales.windows == []
