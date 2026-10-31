import uuid
from datetime import date
from zoneinfo import ZoneInfo

from app.modules.stats.domain.ports import SalesSource
from app.modules.stats.domain.report import Statistics, build_statistics, day_bounds, validate_range


class GetStatistics:
    """The admin's statistics for whole days, `first_day` to `last_day`, in the business's time zone."""

    def __init__(self, source: SalesSource) -> None:
        self._source = source

    async def execute(self, tenant_id: uuid.UUID, first_day: date, last_day: date) -> Statistics:
        validate_range(first_day, last_day)
        zone = ZoneInfo(await self._source.timezone(tenant_id))
        start, end = day_bounds(first_day, last_day, zone)
        return build_statistics(
            first_day,
            last_day,
            zone,
            await self._source.paid_bills(tenant_id, start, end),
            await self._source.sent_orders(tenant_id, start, end),
            await self._source.table_names(tenant_id),
        )
