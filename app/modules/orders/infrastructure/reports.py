import uuid
from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.domain.reports import BillOutcome, ReportedBill, ReportedDish, ReportedOrder
from app.modules.orders.infrastructure.models import BillModel, OrderItemChangeModel, OrderItemModel, OrderModel


class SqlAlchemySalesReports:
    """Rows per bill and per dish; the stats module aggregates them."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def paid_bills(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[ReportedBill]:
        rows = await self._session.execute(
            select(BillModel.closed_at, BillModel.payment_method, BillModel.paid_cents).where(
                BillModel.tenant_id == tenant_id,
                BillModel.payment_method.is_not(None),
                BillModel.closed_at >= start,
                BillModel.closed_at < end,
            )
        )
        return [
            ReportedBill(paid_at=paid_at, payment_method=method, paid_cents=cents or 0)
            for paid_at, method, cents in rows
        ]

    async def sent_orders(self, tenant_id: uuid.UUID, start: datetime, end: datetime) -> list[ReportedOrder]:
        orders = (
            select(OrderModel.id, OrderModel.table_id, OrderModel.created_at, BillModel.closed_at, BillModel.payment_method)
            .join(BillModel, and_(BillModel.id == OrderModel.bill_id, BillModel.tenant_id == OrderModel.tenant_id))
            .where(OrderModel.tenant_id == tenant_id, OrderModel.created_at >= start, OrderModel.created_at < end)
        )
        order_rows = list(await self._session.execute(orders))
        if not order_rows:
            return []

        change = OrderItemChangeModel
        dishes = (
            select(
                OrderItemModel.order_id,
                OrderItemModel.item_id,
                OrderItemModel.name,
                OrderItemModel.quantity,
                OrderItemModel.unit_price_cents,
                OrderItemModel.status,
                OrderItemModel.queued_at,
                func.min(case((change.to_status == "preparing", change.changed_at))),
                func.min(case((change.to_status == "ready", change.changed_at))),
                func.min(case((change.to_status == "delivered", change.changed_at))),
            )
            .outerjoin(change, and_(change.order_item_id == OrderItemModel.id, change.tenant_id == tenant_id))
            .where(
                OrderItemModel.tenant_id == tenant_id,
                OrderItemModel.order_id.in_(select(orders.subquery().c.id)),
            )
            .group_by(OrderItemModel.id)
            .order_by(OrderItemModel.order_id, OrderItemModel.position)
        )
        by_order: dict[uuid.UUID, list[ReportedDish]] = {}
        for order_id, item_id, name, quantity, price, status, queued, preparing, ready, delivered in (
            await self._session.execute(dishes)
        ):
            by_order.setdefault(order_id, []).append(
                ReportedDish(
                    item_id=item_id,
                    name=name,
                    quantity=quantity,
                    unit_price_cents=price,
                    status=status,
                    queued_at=queued,
                    preparing_at=preparing,
                    ready_at=ready,
                    delivered_at=delivered,
                )
            )
        return [
            ReportedOrder(
                table_id=table_id,
                sent_at=sent_at,
                bill=_outcome(closed_at, method),
                dishes=tuple(by_order.get(order_id, [])),
            )
            for order_id, table_id, sent_at, closed_at, method in order_rows
        ]


def _outcome(closed_at: datetime | None, payment_method: str | None) -> BillOutcome:
    if closed_at is None:
        return "open"
    return "paid" if payment_method is not None else "closed"
