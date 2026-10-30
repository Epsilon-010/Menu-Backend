import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from app.modules.orders.application.kitchen import (
    AddDishToOrder,
    ChangeDishStatus,
    GetOrderSettings,
    Kitchen,
    ListDeliveries,
    ListKitchenOrders,
    StaffMember,
    UpdateOrderSettings,
)
from app.modules.orders.domain.errors import (
    BillClosed,
    DishesChanged,
    DishesNotInOrder,
    InvalidOrderData,
    ItemsUnavailable,
    OrderIdTaken,
    OrderNotFound,
    TransitionNotAllowed,
)
from app.modules.orders.domain.model import (
    DEFAULT_LATE_ORDER_MINUTES,
    Bill,
    Order,
    OrderItem,
    OrderItemStatus,
    PaymentMethod,
)
from app.modules.orders.domain.modifiers import MenuModifierGroup, MenuModifierOption
from app.modules.orders.domain.ports import DishChange, MenuItem, TableInfo
from app.shared.domain.principal import Role
from tests.unit.fakes import FakeClock, FakeUnitOfWork

pytestmark = pytest.mark.anyio

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
TABLE = uuid.uuid4()
QUEUED, PREPARING, READY, DELIVERED, CANCELLED = (
    OrderItemStatus.QUEUED,
    OrderItemStatus.PREPARING,
    OrderItemStatus.READY,
    OrderItemStatus.DELIVERED,
    OrderItemStatus.CANCELLED,
)


class InMemoryBills:
    def __init__(self) -> None:
        self.bills: dict[uuid.UUID, Bill] = {}

    async def get(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill | None:
        bill = self.bills.get(bill_id)
        return bill if bill is not None and bill.tenant_id == tenant_id else None


class FakeMenu:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, MenuItem] = {}

    async def orderable(self, tenant_id: uuid.UUID, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, MenuItem]:
        return {item_id: self.items[item_id] for item_id in item_ids if item_id in self.items}


class InMemoryOrders:
    def __init__(self, bills: InMemoryBills) -> None:
        self.orders: dict[uuid.UUID, Order] = {}
        self.history: list[DishChange] = []
        self._bills = bills

    async def add_dish(self, tenant_id: uuid.UUID, order_id: uuid.UUID, dish: OrderItem) -> None:
        if await self.dish_id_taken(dish.id):
            raise OrderIdTaken(dish.id)
        order = self.orders[order_id]
        self.orders[order_id] = replace(order, items=(*order.items, dish))

    async def dish_id_taken(self, dish_id: uuid.UUID) -> bool:
        return any(item.id == dish_id for order in self.orders.values() for item in order.items)

    async def get(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        order = self.orders.get(order_id)
        return order if order is not None and order.tenant_id == tenant_id else None

    async def list_with_dishes_in(self, tenant_id: uuid.UUID, statuses: frozenset[OrderItemStatus]) -> list[Order]:
        return sorted(
            (
                o
                for o in self.orders.values()
                if o.tenant_id == tenant_id
                and self._bills.bills[o.bill_id].is_open
                and any(i.status in statuses for i in o.items)
            ),
            key=lambda o: o.number,
        )

    async def change_dishes(self, tenant_id: uuid.UUID, order_id: uuid.UUID, change: DishChange) -> bool:
        order = self.orders[order_id]
        moving = [item for item in order.items if item.id in change.item_ids]
        if len(moving) != len(change.item_ids) or any(item.status not in change.sources for item in moving):
            return False
        self.orders[order_id] = replace(
            order,
            items=tuple(
                replace(
                    item,
                    status=change.target,
                    updated_at=change.at,
                    ready_at=change.at if change.target is READY else item.ready_at,
                    cancel_reason=change.reason if change.target is CANCELLED else item.cancel_reason,
                )
                if item.id in change.item_ids
                else item
                for item in order.items
            ),
        )
        self.history.append(change)
        return True


class FakeLocks:
    def __init__(self) -> None:
        self.locked: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def lock(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        self.locked.append((tenant_id, table_id))


class FakeTables:
    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> TableInfo | None:
        return TableInfo(name="Table 1", is_active=True, session_version=1)

    async def list_active(self, tenant_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
        return [(TABLE, "Table 1")]


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[tuple[uuid.UUID, uuid.UUID, str, uuid.UUID | None]] = []

    async def publish(
        self,
        tenant_id: uuid.UUID,
        table_id: uuid.UUID,
        kind: str,
        cart_version: int | None = None,
        order_id: uuid.UUID | None = None,
    ) -> None:
        self.published.append((tenant_id, table_id, kind, order_id))


class FakeSettings:
    def __init__(self) -> None:
        self.minutes: dict[uuid.UUID, int] = {}

    async def late_order_minutes(self, tenant_id: uuid.UUID) -> int:
        return self.minutes.get(tenant_id, DEFAULT_LATE_ORDER_MINUTES)

    async def set_late_order_minutes(self, tenant_id: uuid.UUID, minutes: int) -> None:
        self.minutes[tenant_id] = minutes


class World:
    def __init__(self) -> None:
        self.bills = InMemoryBills()
        self.menu = FakeMenu()
        self.orders = InMemoryOrders(self.bills)
        self.locks = FakeLocks()
        self.events = FakeEvents()
        self.settings = FakeSettings()
        self.clock = FakeClock()
        self.uow = FakeUnitOfWork()
        self.ctx = Kitchen(
            locks=self.locks,
            bills=self.bills,
            orders=self.orders,
            menu=self.menu,
            settings=self.settings,
            tables=FakeTables(),
            events=self.events,
            clock=self.clock,
            uow=self.uow,
        )

    def order(self, number: int, *statuses: OrderItemStatus, tenant_id: uuid.UUID = TENANT_A) -> Order:
        bill = Bill(tenant_id=tenant_id, table_id=TABLE, opened_at=self.clock.now())
        self.bills.bills[bill.id] = bill
        order = Order(
            tenant_id=tenant_id,
            table_id=TABLE,
            bill_id=bill.id,
            number=number,
            created_at=self.clock.now(),
            sent_by="Guest 1",
            items=tuple(
                OrderItem(
                    item_id=uuid.uuid4(),
                    name=f"Dish {n}",
                    unit_price_cents=100,
                    quantity=1,
                    note="",
                    added_by="Guest 1",
                    status=status,
                )
                for n, status in enumerate(statuses)
            ),
        )
        self.orders.orders[order.id] = order
        return order

    async def change(
        self, role: Role, order: Order, items: list[OrderItem], target: OrderItemStatus, reason: str | None = None
    ) -> Order:
        staff = StaffMember(tenant_id=TENANT_A, user_id=uuid.uuid4(), role=role)
        result = await ChangeDishStatus(self.ctx).execute(staff, order.id, [i.id for i in items], target, reason)
        return result.order

    def pay(self, order: Order) -> None:
        bill = self.bills.bills[order.bill_id]
        self.bills.bills[bill.id] = bill.paid(self.clock.now(), PaymentMethod.CASH, order.total_cents)

    def menu_item(self, name: str, price_cents: int) -> uuid.UUID:
        item_id = uuid.uuid4()
        self.menu.items[item_id] = MenuItem(item_id=item_id, name=name, price_cents=price_cents)
        return item_id


async def test_the_kitchen_marks_several_dishes_of_one_order_at_once() -> None:
    world = World()
    order = world.order(1, QUEUED, QUEUED, QUEUED)

    changed = await world.change(Role.KITCHEN, order, list(order.items[:2]), READY)

    assert [item.status for item in changed.items] == [READY, READY, QUEUED]
    assert changed.items[0].ready_at == world.clock.now()
    assert world.locks.locked == [(TENANT_A, TABLE)]
    assert world.uow.commits == 1
    assert world.events.published == [(TENANT_A, TABLE, "order.updated", order.id)]
    assert world.orders.history[0].at == world.clock.now()


async def test_an_order_of_another_tenant_is_not_found() -> None:
    world = World()
    order = world.order(1, QUEUED, tenant_id=TENANT_B)

    with pytest.raises(OrderNotFound):
        await world.change(Role.ADMIN, order, list(order.items), PREPARING)
    assert world.orders.orders[order.id] == order


async def test_dishes_of_another_order_are_rejected_before_the_role() -> None:
    world = World()
    order, other = world.order(1, QUEUED), world.order(2, QUEUED)

    with pytest.raises(DishesNotInOrder):
        # A waiter cannot mark preparing either: the foreign dish is reported first.
        await world.change(Role.WAITER, order, [order.items[0], other.items[0]], PREPARING)
    assert world.uow.commits == 0


@pytest.mark.parametrize("role, target", [(Role.WAITER, PREPARING), (Role.WAITER, READY), (Role.KITCHEN, DELIVERED)])
async def test_a_role_outside_the_matrix_cannot_mark_dishes(role: Role, target: OrderItemStatus) -> None:
    world = World()
    order = world.order(1, READY if target is DELIVERED else QUEUED)

    with pytest.raises(TransitionNotAllowed):
        await world.change(role, order, list(order.items), target)
    assert world.locks.locked == []


async def test_one_dish_in_a_wrong_state_changes_none_and_publishes_nothing() -> None:
    world = World()
    order = world.order(1, QUEUED, DELIVERED)

    with pytest.raises(DishesChanged):
        await world.change(Role.ADMIN, order, list(order.items), PREPARING)
    assert world.orders.orders[order.id] == order
    assert (world.uow.commits, world.events.published) == (0, [])


async def test_cancelling_keeps_the_reason_and_requires_it() -> None:
    world = World()
    order = world.order(1, QUEUED)

    with pytest.raises(InvalidOrderData):
        await world.change(Role.KITCHEN, order, list(order.items), CANCELLED)
    changed = await world.change(Role.KITCHEN, order, list(order.items), CANCELLED, " no avocado ")

    assert changed.items[0].cancel_reason == "no avocado"
    assert world.orders.history[0].reason == "no avocado"


async def test_the_kitchen_queue_has_orders_with_pending_dishes_by_number() -> None:
    world = World()
    second = world.order(2, READY, PREPARING)
    world.order(3, DELIVERED, CANCELLED)
    first = world.order(1, QUEUED)
    world.order(1, QUEUED, tenant_id=TENANT_B)

    queue = await ListKitchenOrders(world.ctx).execute(TENANT_A)

    assert [(view.order.id, view.table_name) for view in queue] == [(first.id, "Table 1"), (second.id, "Table 1")]


async def test_deliveries_are_sorted_by_their_oldest_ready_dish() -> None:
    world = World()
    early, late = world.order(1, QUEUED), world.order(2, QUEUED, QUEUED)
    world.order(3, PREPARING)
    await world.change(Role.KITCHEN, late, [late.items[0]], READY)
    world.clock.advance(timedelta(minutes=1))
    await world.change(Role.KITCHEN, early, list(early.items), READY)
    world.clock.advance(timedelta(minutes=1))
    await world.change(Role.KITCHEN, late, [late.items[1]], READY)

    queue = await ListDeliveries(world.ctx).execute(TENANT_A)

    assert [view.order.number for view in queue] == [2, 1]


async def test_the_late_order_threshold_defaults_to_15_minutes_per_tenant() -> None:
    world = World()

    assert DEFAULT_LATE_ORDER_MINUTES == 15
    assert await GetOrderSettings(world.ctx).execute(TENANT_A) == 15
    assert await UpdateOrderSettings(world.ctx).execute(TENANT_A, 30) == 30
    assert await GetOrderSettings(world.ctx).execute(TENANT_A) == 30
    assert await GetOrderSettings(world.ctx).execute(TENANT_B) == 15
    for out_of_range in (0, 241):
        with pytest.raises(InvalidOrderData):
            await UpdateOrderSettings(world.ctx).execute(TENANT_A, out_of_range)


@pytest.mark.parametrize("target", [PREPARING, READY, DELIVERED, CANCELLED])
async def test_no_dish_of_a_paid_bill_changes(target: OrderItemStatus) -> None:
    world = World()
    order = world.order(1, READY if target is DELIVERED else QUEUED)
    world.pay(order)

    with pytest.raises(BillClosed):
        await world.change(Role.ADMIN, order, list(order.items), target, "Left" if target is CANCELLED else None)
    assert world.orders.orders[order.id] == order
    assert (world.orders.history, world.uow.commits, world.events.published) == ([], 0, [])


async def test_paid_orders_leave_both_queues() -> None:
    world = World()
    paid, open_order = world.order(1, QUEUED, READY), world.order(2, QUEUED, READY)
    world.pay(paid)

    assert [view.order.id for view in await ListKitchenOrders(world.ctx).execute(TENANT_A)] == [open_order.id]
    assert [view.order.id for view in await ListDeliveries(world.ctx).execute(TENANT_A)] == [open_order.id]


async def test_staff_add_a_queued_dish_at_the_menu_price() -> None:
    world = World()
    order = world.order(1, QUEUED)
    taco = world.menu_item("Taco", 1800)

    added = await AddDishToOrder(world.ctx).execute(TENANT_A, order.id, taco, 2, " no onion ")

    assert added.created
    dish = added.order.items[-1]
    assert (dish.name, dish.unit_price_cents, dish.quantity, dish.note) == ("Taco", 1800, 2, "no onion")
    assert (dish.status, dish.added_by) == (QUEUED, "Staff")
    assert world.locks.locked == [(TENANT_A, TABLE)]
    assert world.uow.commits == 1
    assert world.events.published == [(TENANT_A, TABLE, "order.updated", order.id)]


async def test_staff_add_a_dish_with_its_options_priced_by_the_menu() -> None:
    world = World()
    order = world.order(1, QUEUED)
    small = MenuModifierOption(option_id=uuid.uuid4(), name="Small", price_cents=0)
    large = MenuModifierOption(option_id=uuid.uuid4(), name="Large", price_cents=700)
    size = MenuModifierGroup(group_id=uuid.uuid4(), name="Size", min_select=1, max_select=1, options=(small, large))
    taco = world.menu_item("Taco", 1800)
    world.menu.items[taco] = replace(world.menu.items[taco], modifier_groups=(size,))
    add = AddDishToOrder(world.ctx)
    dish_id = uuid.uuid4()

    added = await add.execute(TENANT_A, order.id, taco, 2, dish_id=dish_id, modifier_option_ids=(large.option_id,))
    again = await add.execute(TENANT_A, order.id, taco, 2, dish_id=dish_id, modifier_option_ids=(large.option_id,))

    dish = added.order.items[-1]
    assert (dish.unit_price_cents, dish.subtotal_cents) == (2500, 5000)
    assert [(m.group, m.name, m.price_cents) for m in dish.modifiers] == [("Size", "Large", 700)]
    assert not again.created
    with pytest.raises(OrderIdTaken):
        await add.execute(TENANT_A, order.id, taco, 2, dish_id=dish_id, modifier_option_ids=(small.option_id,))
    with pytest.raises(InvalidOrderData, match="Choose 1 option for Size"):
        await add.execute(TENANT_A, order.id, taco, 1)
    assert world.uow.commits == 1


async def test_adding_needs_an_orderable_item_an_open_bill_and_a_known_order() -> None:
    world = World()
    order = world.order(1, QUEUED)
    taco = world.menu_item("Taco", 1800)
    add = AddDishToOrder(world.ctx)

    with pytest.raises(ItemsUnavailable):
        await add.execute(TENANT_A, order.id, uuid.uuid4(), 1)
    with pytest.raises(OrderNotFound):
        await add.execute(TENANT_B, order.id, taco, 1)
    world.pay(order)
    with pytest.raises(BillClosed):
        await add.execute(TENANT_A, order.id, taco, 1)
    assert world.orders.orders[order.id] == order
    assert world.uow.commits == 0


async def test_repeating_an_add_returns_the_order_and_a_reused_id_is_taken() -> None:
    world = World()
    order, other = world.order(1, QUEUED), world.order(2, QUEUED)
    taco = world.menu_item("Taco", 1800)
    add = AddDishToOrder(world.ctx)
    dish_id = uuid.uuid4()

    first = await add.execute(TENANT_A, order.id, taco, 1, dish_id=dish_id)
    again = await add.execute(TENANT_A, order.id, taco, 1, dish_id=dish_id)

    assert again == replace(first, created=False)
    with pytest.raises(OrderIdTaken):
        await add.execute(TENANT_A, order.id, taco, 2, dish_id=dish_id)
    with pytest.raises(OrderIdTaken):
        await add.execute(TENANT_A, other.id, taco, 1, dish_id=dish_id)
    assert world.uow.commits == 1
