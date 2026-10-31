"""What the waiter (or admin) does with a table's bill: open the table, see what it owes, take the payment.

Paying or closing takes the same table lock as the cart and the orders, ends every guest of the visit
and discards the unsent cart, all in one transaction: after that nobody at the table can order on it.
"""

import uuid
from dataclasses import dataclass

from app.modules.orders.application.ordering import Ordering, clear_bill_request
from app.modules.orders.domain.errors import BillHasOrders, BillNotFound, NothingToCharge, TableNotFound
from app.modules.orders.domain.model import Bill, Order, PaymentMethod


@dataclass(frozen=True)
class BillDetail:
    bill: Bill
    table_name: str
    orders: list[Order]

    @property
    def total_cents(self) -> int:
        return sum(order.total_cents for order in self.orders)


@dataclass(frozen=True)
class TableOverview:
    table_id: uuid.UUID
    table_name: str
    bill: BillDetail | None


async def _table_name(ctx: Ordering, tenant_id: uuid.UUID, table_id: uuid.UUID) -> str:
    table = await ctx.tables.get(tenant_id, table_id)
    if table is None or not table.is_active:
        raise TableNotFound(table_id)
    return table.name


class OpenTable:
    """Opens the table's bill so its QR lets guests in; opening an open table returns its bill."""

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> BillDetail:
        ctx = self._ctx
        await ctx.locks.lock(tenant_id, table_id)
        name = await _table_name(ctx, tenant_id, table_id)
        bill = await ctx.bills.get_open(tenant_id, table_id)
        if bill is not None:
            return BillDetail(bill=bill, table_name=name, orders=await ctx.orders.list_for_bill(tenant_id, bill.id))
        bill = Bill(tenant_id=tenant_id, table_id=table_id, opened_at=ctx.clock.now())
        await ctx.bills.add(bill)
        await ctx.uow.commit()
        await ctx.events.publish(tenant_id, table_id, "bill.opened")
        return BillDetail(bill=bill, table_name=name, orders=[])


class ListTables:
    """Every active table of the tenant, with its open bill and what it owes so far."""

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID) -> list[TableOverview]:
        ctx = self._ctx
        open_bills = {bill.table_id: bill for bill in await ctx.bills.list_open(tenant_id)}
        overview = []
        for table_id, name in await ctx.tables.list_active(tenant_id):
            bill = open_bills.get(table_id)
            detail = (
                BillDetail(bill=bill, table_name=name, orders=await ctx.orders.list_for_bill(tenant_id, bill.id))
                if bill is not None
                else None
            )
            overview.append(TableOverview(table_id=table_id, table_name=name, bill=detail))
        return overview


async def _locked_open_bill(ctx: Ordering, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill:
    bill = await ctx.bills.get(tenant_id, bill_id)
    if bill is None:
        raise BillNotFound(bill_id)
    await ctx.locks.lock(tenant_id, bill.table_id)
    # Read again under the lock: a concurrent payment may have closed it meanwhile.
    bill = await ctx.bills.get(tenant_id, bill_id)
    if bill is None or not bill.is_open:
        raise BillNotFound(bill_id)
    return bill


async def _end_visit(ctx: Ordering, closed: Bill) -> None:
    """Stores the closed bill, ends its guests and discards the unsent cart; commits and notifies."""
    await ctx.bills.update(closed)
    guest_ids = await ctx.guests.end_all_for_table(closed.tenant_id, closed.table_id, ctx.clock.now())
    await ctx.carts.clear(closed.tenant_id, closed.table_id)
    version = await ctx.carts.bump_version(closed.tenant_id, closed.table_id)
    await ctx.uow.commit()
    await ctx.guest_access.end_access(guest_ids)
    await ctx.events.publish(closed.tenant_id, closed.table_id, "bill.closed")
    await ctx.events.publish(closed.tenant_id, closed.table_id, "cart.updated", cart_version=version)


class GetBill:
    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> BillDetail:
        ctx = self._ctx
        bill = await ctx.bills.get(tenant_id, bill_id)
        if bill is None:
            raise BillNotFound(bill_id)
        table = await ctx.tables.get(tenant_id, bill.table_id)
        return BillDetail(
            bill=bill,
            table_name=table.name if table is not None else "",
            orders=await ctx.orders.list_for_bill(tenant_id, bill.id),
        )


class PayBill:
    """Registers the payment of the backend-computed total and closes the bill."""

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID, bill_id: uuid.UUID, method: PaymentMethod) -> BillDetail:
        ctx = self._ctx
        bill = await _locked_open_bill(ctx, tenant_id, bill_id)
        orders = await ctx.orders.list_for_bill(tenant_id, bill.id)
        total = sum(order.total_cents for order in orders)
        if total == 0:
            raise NothingToCharge(bill_id)
        paid = bill.paid(ctx.clock.now(), method, total)
        await _end_visit(ctx, paid)
        table = await ctx.tables.get(tenant_id, bill.table_id)
        return BillDetail(bill=paid, table_name=table.name if table is not None else "", orders=orders)


class CloseTable:
    """Closes a bill with nothing to charge: no orders (the guests left) or every dish cancelled."""

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> None:
        ctx = self._ctx
        bill = await _locked_open_bill(ctx, tenant_id, bill_id)
        if sum(order.total_cents for order in await ctx.orders.list_for_bill(tenant_id, bill.id)) > 0:
            raise BillHasOrders(bill_id)
        await _end_visit(ctx, bill.closed_without_payment(ctx.clock.now()))


class DismissBillRequest:
    """The waiter attends the table that asked for the bill; the alert goes away for every waiter."""

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> None:
        ctx = self._ctx
        bill = await _locked_open_bill(ctx, tenant_id, bill_id)
        if bill.bill_requested_at is not None:
            await clear_bill_request(ctx, bill)
