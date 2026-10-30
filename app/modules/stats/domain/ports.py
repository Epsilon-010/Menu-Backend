import uuid
from datetime import datetime
from typing import Protocol

from app.modules.stats.domain.report import PaidBill, SentOrder


class SalesSource(Protocol):
    """Raw sales records of one tenant; `start` inclusive, `end` exclusive."""

    async def timezone(self, tenant_id: uuid.UUID) -> str: ...

    async def paid_bills(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[PaidBill]: ...

    async def sent_orders(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[SentOrder]: ...

    async def table_names(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, str]: ...
