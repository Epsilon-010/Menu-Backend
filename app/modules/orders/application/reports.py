import uuid
from datetime import datetime

from app.modules.orders.domain.reports import ReportedBill, ReportedOrder, SalesReports


class ReportSales:
    """Read-only sales records of one tenant for a time window, for other modules' reports."""

    def __init__(self, reports: SalesReports) -> None:
        self._reports = reports

    async def paid_bills(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[ReportedBill]:
        return await self._reports.paid_bills(tenant_id, start, end)

    async def sent_orders(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[ReportedOrder]:
        return await self._reports.sent_orders(tenant_id, start, end)
