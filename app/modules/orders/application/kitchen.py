"""What the staff does with the dishes of sent orders: the kitchen prepares and releases them, waiters
deliver them, and anyone may cancel one nobody started.

Everything is grouped by order. A status change takes the order's table lock first (the same one paying
the bill takes), then moves every requested dish with one update conditioned on the states it may come
from: either all of them change, or none does.

A paid bill is frozen: its dishes never change again and its orders leave the queues. While the bill is
open, waiters (and admins) may add a dish to a sent order; it is priced from the menu like a sent cart.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.orders.domain.errors import (
    BillClosed,
    DishesChanged,
    DishesNotInOrder,
    ItemsUnavailable,
    OrderIdTaken,
    OrderNotFound,
)
from app.modules.orders.domain.model import (
    STAFF_NAME,
    Order,
    OrderItem,
    OrderItemStatus,
    sources_for,
    validate_change_reason,
    validate_late_order_minutes,
    validate_note,
    validate_quantity,
)
from app.modules.orders.domain.modifiers import choose_modifiers, unit_price, validate_option_ids
from app.modules.orders.domain.ports import (
    BillRepository,
    DishChange,
    Menu,
    OrderRepository,
    OrderSettingsRepository,
    TableEvents,
    TableLocks,
    Tables,
)
from app.shared.domain.ports import Clock, UnitOfWork
from app.shared.domain.principal import Role

KITCHEN_STATUSES = frozenset({OrderItemStatus.QUEUED, OrderItemStatus.PREPARING})
DELIVERY_STATUSES = frozenset({OrderItemStatus.READY})


@dataclass(frozen=True)
class Kitchen:
    """Everything the staff order use cases share; built once per request by the infrastructure."""

    locks: TableLocks
    bills: BillRepository
    orders: OrderRepository
    menu: Menu
    settings: OrderSettingsRepository
    tables: Tables
    events: TableEvents
    clock: Clock
    uow: UnitOfWork


@dataclass(frozen=True)
class StaffMember:
    """The staff member acting, from the access token."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: Role


@dataclass(frozen=True)
class StaffOrder:
    order: Order
    table_name: str


async def _with_table_names(ctx: Kitchen, tenant_id: uuid.UUID, orders: list[Order]) -> list[StaffOrder]:
    names = dict(await ctx.tables.list_active(tenant_id))
    for table_id in {order.table_id for order in orders} - names.keys():
        # A table deactivated while its orders are still being served keeps its name.
        table = await ctx.tables.get(tenant_id, table_id)
        names[table_id] = table.name if table is not None else ""
    return [StaffOrder(order=order, table_name=names[order.table_id]) for order in orders]


async def _require_open_bill(ctx: Kitchen, order: Order) -> None:
    """Call it under the table lock: paying takes the same lock, so the bill cannot close meanwhile."""
    bill = await ctx.bills.get(order.tenant_id, order.bill_id)
    if bill is None or not bill.is_open:
        raise BillClosed(order.bill_id)


class ListKitchenOrders:
    """Orders with a dish still queued or in preparation, by arrival (a suggestion: any may go first)."""

    def __init__(self, ctx: Kitchen) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID) -> list[StaffOrder]:
        orders = await self._ctx.orders.list_with_dishes_in(tenant_id, KITCHEN_STATUSES)
        return await _with_table_names(self._ctx, tenant_id, orders)


def _oldest_ready(order: Order) -> datetime:
    return min(item.ready_at or order.created_at for item in order.items if item.status is OrderItemStatus.READY)


class ListDeliveries:
    """Orders with a dish ready to take to the table, the one waiting longest first."""

    def __init__(self, ctx: Kitchen) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID) -> list[StaffOrder]:
        orders = await self._ctx.orders.list_with_dishes_in(tenant_id, DELIVERY_STATUSES)
        orders.sort(key=lambda order: (_oldest_ready(order), order.number))
        return await _with_table_names(self._ctx, tenant_id, orders)


class ChangeDishStatus:
    """Moves one or more dishes of one order to a status, all or nothing, only as the caller's role may."""

    def __init__(self, ctx: Kitchen) -> None:
        self._ctx = ctx

    async def execute(
        self,
        staff: StaffMember,
        order_id: uuid.UUID,
        item_ids: list[uuid.UUID],
        target: OrderItemStatus,
        reason: str | None = None,
    ) -> StaffOrder:
        ctx = self._ctx
        reason = validate_change_reason(target, reason)
        order = await ctx.orders.get(staff.tenant_id, order_id)
        if order is None:
            raise OrderNotFound(order_id)
        if not set(item_ids) <= {item.id for item in order.items}:
            raise DishesNotInOrder(order_id)
        sources = sources_for(target, staff.role)

        await ctx.locks.lock(staff.tenant_id, order.table_id)
        await _require_open_bill(ctx, order)
        change = DishChange(
            item_ids=frozenset(item_ids),
            sources=sources,
            target=target,
            changed_by=staff.user_id,
            at=ctx.clock.now(),
            reason=reason,
        )
        if not await ctx.orders.change_dishes(staff.tenant_id, order.id, change):
            raise DishesChanged(order_id)
        await ctx.uow.commit()
        await ctx.events.publish(staff.tenant_id, order.table_id, "order.updated", order_id=order.id)
        changed = await ctx.orders.get(staff.tenant_id, order.id)
        return (await _with_table_names(ctx, staff.tenant_id, [changed or order]))[0]


@dataclass(frozen=True)
class AddedDish:
    order: Order
    # False when the call repeated an add that had already been made (same id, same dish).
    created: bool


class AddDishToOrder:
    """Adds a queued dish to an order of an open bill at the current menu price (never the client's).

    `dish_id` makes it idempotent: repeating the same add returns the order unchanged.
    """

    def __init__(self, ctx: Kitchen) -> None:
        self._ctx = ctx

    async def execute(
        self,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        quantity: int,
        note: str = "",
        dish_id: uuid.UUID | None = None,
        modifier_option_ids: tuple[uuid.UUID, ...] = (),
    ) -> AddedDish:
        ctx = self._ctx
        quantity, note = validate_quantity(quantity), validate_note(note)
        modifier_option_ids = validate_option_ids(modifier_option_ids)
        order = await ctx.orders.get(tenant_id, order_id)
        if order is None:
            raise OrderNotFound(order_id)
        await ctx.locks.lock(tenant_id, order.table_id)
        # Read again under the lock: a concurrent add may have changed it.
        order = await ctx.orders.get(tenant_id, order_id) or order
        if dish_id is not None:
            existing = next((item for item in order.items if item.id == dish_id), None)
            chosen_before = frozenset(modifier.option_id for modifier in existing.modifiers) if existing else None
            if existing is not None and (existing.item_id, existing.quantity, existing.note, chosen_before) == (
                item_id,
                quantity,
                note,
                frozenset(modifier_option_ids),
            ):
                return AddedDish(order=order, created=False)
            if existing is not None or await ctx.orders.dish_id_taken(dish_id):
                raise OrderIdTaken(dish_id)
        await _require_open_bill(ctx, order)
        item = (await ctx.menu.orderable(tenant_id, {item_id})).get(item_id)
        if item is None:
            raise ItemsUnavailable([item_id])
        chosen = choose_modifiers(item, modifier_option_ids)
        now = ctx.clock.now()
        await ctx.orders.add_dish(
            tenant_id,
            order.id,
            OrderItem(
                item_id=item_id,
                name=item.name,
                unit_price_cents=unit_price(item, chosen),
                quantity=quantity,
                note=note,
                added_by=STAFF_NAME,
                updated_at=now,
                modifiers=chosen,
                id=dish_id or uuid.uuid4(),
            ),
        )
        await ctx.uow.commit()
        await ctx.events.publish(tenant_id, order.table_id, "order.updated", order_id=order.id)
        return AddedDish(order=await ctx.orders.get(tenant_id, order.id) or order, created=True)


class GetOrderSettings:
    """Minutes after which an order counts as late."""

    def __init__(self, ctx: Kitchen) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID) -> int:
        return await self._ctx.settings.late_order_minutes(tenant_id)


class UpdateOrderSettings:
    def __init__(self, ctx: Kitchen) -> None:
        self._ctx = ctx

    async def execute(self, tenant_id: uuid.UUID, late_order_minutes: int) -> int:
        minutes = validate_late_order_minutes(late_order_minutes)
        await self._ctx.settings.set_late_order_minutes(tenant_id, minutes)
        await self._ctx.uow.commit()
        return minutes
