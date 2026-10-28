"""What a table does: read and edit its shared cart, send it as one order, and follow its orders.

Every write first takes the table's lock and checks, in that same transaction, that the caller may
still act: an active tablet whose PIN did not change, or a guest whose visit is still open. Paying the
bill takes the same lock, so nothing can be added or sent once it has been paid.
"""

import uuid
from dataclasses import dataclass

from app.modules.orders.domain.errors import (
    CartChanged,
    CartEmpty,
    CartFull,
    CartLineNotFound,
    DinerNotAllowed,
    ItemsUnavailable,
    OrderIdTaken,
)
from app.modules.orders.domain.model import (
    MAX_CART_LINES,
    Bill,
    CartLine,
    Diner,
    Order,
    OrderItem,
    validate_note,
    validate_quantity,
)
from app.modules.orders.domain.ports import (
    BillRepository,
    CartRepository,
    GuestAccess,
    GuestRepository,
    Menu,
    OrderRepository,
    TableEvents,
    TableLocks,
    Tables,
)
from app.shared.domain.ports import Clock, UnitOfWork

TABLET_NAME = "Tablet"


@dataclass(frozen=True)
class Ordering:
    """Everything the ordering use cases share; built once per request by the infrastructure."""

    locks: TableLocks
    bills: BillRepository
    guests: GuestRepository
    carts: CartRepository
    orders: OrderRepository
    menu: Menu
    tables: Tables
    guest_access: GuestAccess
    events: TableEvents
    clock: Clock
    uow: UnitOfWork


@dataclass(frozen=True)
class CartLineView:
    line: CartLine
    available: bool
    unit_price_cents: int | None

    @property
    def subtotal_cents(self) -> int:
        return (self.unit_price_cents or 0) * self.line.quantity


@dataclass(frozen=True)
class CartView:
    version: int
    lines: list[CartLineView]

    @property
    def total_cents(self) -> int:
        return sum(line.subtotal_cents for line in self.lines if line.available)


@dataclass(frozen=True)
class Visit:
    """The authorized caller: who they are at the table and the table's open bill, if any."""

    actor: str
    bill: Bill | None


async def authorize(ctx: Ordering, diner: Diner, *, lock: bool) -> Visit:
    """Raises DinerNotAllowed unless the caller may act at the table right now (see the module docs)."""
    if lock:
        await ctx.locks.lock(diner.tenant_id, diner.table_id)
    table = await ctx.tables.get(diner.tenant_id, diner.table_id)
    if table is None or not table.is_active:
        raise DinerNotAllowed()
    bill = await ctx.bills.get_open(diner.tenant_id, diner.table_id)
    if diner.guest_id is None:
        if table.session_version != diner.session_version:
            raise DinerNotAllowed()
        return Visit(actor=TABLET_NAME, bill=bill)

    guest = await ctx.guests.get(diner.tenant_id, diner.guest_id)
    if (
        guest is None
        or not guest.is_active_at(ctx.clock.now())
        or guest.table_id != diner.table_id
        or bill is None
        or guest.bill_id != bill.id
        or diner.bill_id != bill.id
    ):
        raise DinerNotAllowed()
    return Visit(actor=guest.name, bill=bill)


async def _cart_view(ctx: Ordering, diner: Diner) -> CartView:
    cart = await ctx.carts.get(diner.tenant_id, diner.table_id)
    prices = await ctx.menu.orderable(diner.tenant_id, {line.item_id for line in cart.lines})
    return CartView(
        version=cart.version,
        lines=[
            CartLineView(
                line=line,
                available=line.item_id in prices,
                unit_price_cents=prices[line.item_id].price_cents if line.item_id in prices else None,
            )
            for line in cart.lines
        ],
    )


async def _cart_changed(ctx: Ordering, diner: Diner) -> CartView:
    version = await ctx.carts.bump_version(diner.tenant_id, diner.table_id)
    await ctx.uow.commit()
    await ctx.events.publish(diner.tenant_id, diner.table_id, "cart.updated", cart_version=version)
    return await _cart_view(ctx, diner)


class GetCart:
    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, diner: Diner) -> CartView:
        await authorize(self._ctx, diner, lock=False)
        return await _cart_view(self._ctx, diner)


class AddCartLine:
    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(
        self, diner: Diner, item_id: uuid.UUID, quantity: int, note: str = "", line_id: uuid.UUID | None = None
    ) -> CartView:
        """`line_id` makes the add idempotent: a repeat (even after the cart was sent) adds nothing."""
        ctx = self._ctx
        quantity, note = validate_quantity(quantity), validate_note(note)
        visit = await authorize(ctx, diner, lock=True)
        if line_id is not None:
            existing = await ctx.carts.get_line(diner.tenant_id, line_id)
            if existing is not None and existing.table_id == diner.table_id and existing.same_request(
                item_id, quantity, note
            ):
                return await _cart_view(ctx, diner)
            if existing is not None or await ctx.carts.line_exists_anywhere(line_id):
                # Also a line already sent in an order: answered as a clash, never added twice.
                raise OrderIdTaken(line_id)

        item = (await ctx.menu.orderable(diner.tenant_id, {item_id})).get(item_id)
        if item is None:
            raise ItemsUnavailable([item_id])
        cart = await ctx.carts.get(diner.tenant_id, diner.table_id)
        if len(cart.lines) >= MAX_CART_LINES:
            raise CartFull()
        await ctx.carts.add_line(
            CartLine(
                tenant_id=diner.tenant_id,
                table_id=diner.table_id,
                item_id=item_id,
                item_name=item.name,
                quantity=quantity,
                note=note,
                added_by=visit.actor,
                created_at=ctx.clock.now(),
                id=line_id or uuid.uuid4(),
            )
        )
        return await _cart_changed(ctx, diner)


async def _own_line(ctx: Ordering, diner: Diner, line_id: uuid.UUID) -> CartLine:
    line = await ctx.carts.get_line(diner.tenant_id, line_id)
    if line is None or line.table_id != diner.table_id:
        raise CartLineNotFound(line_id)
    return line


class UpdateCartLine:
    """Anyone at the table may change any line: it is one shared cart."""

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(
        self, diner: Diner, line_id: uuid.UUID, quantity: int | None = None, note: str | None = None
    ) -> CartView:
        await authorize(self._ctx, diner, lock=True)
        line = await _own_line(self._ctx, diner, line_id)
        await self._ctx.carts.update_line(line.with_changes(quantity=quantity, note=note))
        return await _cart_changed(self._ctx, diner)


class RemoveCartLine:
    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, diner: Diner, line_id: uuid.UUID) -> CartView:
        await authorize(self._ctx, diner, lock=True)
        await _own_line(self._ctx, diner, line_id)
        await self._ctx.carts.delete_line(diner.tenant_id, line_id)
        return await _cart_changed(self._ctx, diner)


class SubmitCart:
    """Sends the whole cart as one order, only if it is still the version the sender confirmed.

    The order takes the current menu prices (never the client's) and goes on the table's open bill;
    the tablet's first order opens one. The cart is left empty for the next round.
    """

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, diner: Diner, expected_version: int, order_id: uuid.UUID | None = None) -> Order:
        ctx = self._ctx
        visit = await authorize(ctx, diner, lock=True)
        if order_id is not None:
            existing = await ctx.orders.get(diner.tenant_id, order_id)
            if existing is not None and existing.table_id == diner.table_id:
                return existing
            if existing is not None or await ctx.orders.exists_anywhere(order_id):
                raise OrderIdTaken(order_id)

        cart = await ctx.carts.get(diner.tenant_id, diner.table_id)
        if cart.version != expected_version:
            raise CartChanged()
        if not cart.lines:
            raise CartEmpty()
        prices = await ctx.menu.orderable(diner.tenant_id, {line.item_id for line in cart.lines})
        missing = [line.item_id for line in cart.lines if line.item_id not in prices]
        if missing:
            raise ItemsUnavailable(missing)

        now = ctx.clock.now()
        bill = visit.bill
        if bill is None:
            bill = Bill(tenant_id=diner.tenant_id, table_id=diner.table_id, opened_at=now)
            await ctx.bills.add(bill)
        order = Order(
            tenant_id=diner.tenant_id,
            table_id=diner.table_id,
            bill_id=bill.id,
            number=await ctx.orders.next_number(diner.tenant_id),
            created_at=now,
            sent_by=visit.actor,
            items=tuple(
                OrderItem(
                    item_id=line.item_id,
                    name=prices[line.item_id].name,
                    unit_price_cents=prices[line.item_id].price_cents,
                    quantity=line.quantity,
                    note=line.note,
                    added_by=line.added_by,
                    id=line.id,
                )
                for line in cart.lines
            ),
            id=order_id or uuid.uuid4(),
        )
        await ctx.orders.add(order)
        await ctx.carts.clear(diner.tenant_id, diner.table_id)
        version = await ctx.carts.bump_version(diner.tenant_id, diner.table_id)
        await ctx.uow.commit()
        await ctx.events.publish(diner.tenant_id, diner.table_id, "order.created")
        await ctx.events.publish(diner.tenant_id, diner.table_id, "cart.updated", cart_version=version)
        return order


class ListTableOrders:
    """The orders of the table's open bill (for a guest: the visit they joined), oldest first."""

    def __init__(self, ctx: Ordering) -> None:
        self._ctx = ctx

    async def execute(self, diner: Diner) -> list[Order]:
        visit = await authorize(self._ctx, diner, lock=False)
        if visit.bill is None:
            return []
        return await self._ctx.orders.list_for_bill(diner.tenant_id, visit.bill.id)
