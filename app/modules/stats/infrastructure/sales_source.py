import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.reports import ReportSales
from app.modules.orders.domain.reports import ReportedOrder
from app.modules.orders.infrastructure.reports import SqlAlchemySalesReports
from app.modules.stats.domain.report import BillState, PaidBill, SentDish, SentOrder
from app.modules.tables.application.manage_tables import ListTables
from app.modules.tables.infrastructure.repository import SqlAlchemyTableRepository
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.tenant import DEFAULT_TIMEZONE
from app.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository


class ModulesSalesSource:
    """Reads the other modules through their application layer, never their tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._sales = ReportSales(SqlAlchemySalesReports(session))
        self._tables = ListTables(SqlAlchemyTableRepository(session))
        self._tenants = GetTenant(SqlAlchemyTenantRepository(session))

    async def timezone(self, tenant_id: uuid.UUID) -> str:
        tenant = await self._tenants.execute(tenant_id)
        return tenant.timezone if tenant is not None else DEFAULT_TIMEZONE

    async def paid_bills(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[PaidBill]:
        return [
            PaidBill(paid_at=bill.paid_at, method=bill.payment_method, amount_cents=bill.paid_cents)
            for bill in await self._sales.paid_bills(tenant_id, start, end)
        ]

    async def sent_orders(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[SentOrder]:
        return [_order(order) for order in await self._sales.sent_orders(tenant_id, start, end)]

    async def table_names(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, str]:
        return {table.id: table.name for table in await self._tables.execute(tenant_id)}


def _order(order: ReportedOrder) -> SentOrder:
    return SentOrder(
        table_id=order.table_id,
        sent_at=order.sent_at,
        bill_state=BillState(order.bill),
        dishes=tuple(
            SentDish(
                item_id=dish.item_id,
                name=dish.name,
                quantity=dish.quantity,
                subtotal_cents=dish.unit_price_cents * dish.quantity,
                cancelled=dish.status == "cancelled",
                queued_at=dish.queued_at,
                preparing_at=dish.preparing_at,
                ready_at=dish.ready_at,
                delivered_at=dish.delivered_at,
            )
            for dish in order.dishes
        ),
    )
