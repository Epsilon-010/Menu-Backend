import uuid
from datetime import datetime

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.domain.model import (
    Bill,
    Cart,
    CartLine,
    Guest,
    Order,
    OrderItem,
    OrderItemStatus,
    PaymentMethod,
)
from app.modules.orders.infrastructure.models import (
    BillModel,
    CartLineModel,
    CartModel,
    GuestModel,
    OrderCounterModel,
    OrderItemModel,
    OrderModel,
)
from app.shared.infrastructure.database import advisory_xact_lock


class PostgresTableLocks:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        await advisory_xact_lock(self._session, f"table-visit:{tenant_id}:{table_id}")


def _bill(model: BillModel) -> Bill:
    return Bill(
        id=model.id,
        tenant_id=model.tenant_id,
        table_id=model.table_id,
        opened_at=model.opened_at,
        closed_at=model.closed_at,
        payment_method=PaymentMethod(model.payment_method) if model.payment_method else None,
        paid_cents=model.paid_cents,
    )


class SqlAlchemyBillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, bill: Bill) -> None:
        self._session.add(
            BillModel(id=bill.id, tenant_id=bill.tenant_id, table_id=bill.table_id, opened_at=bill.opened_at)
        )
        await self._session.flush()

    async def get(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill | None:
        model = await self._session.scalar(
            select(BillModel).where(BillModel.tenant_id == tenant_id, BillModel.id == bill_id)
        )
        return _bill(model) if model is not None else None

    async def get_open(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Bill | None:
        model = await self._session.scalar(
            select(BillModel).where(
                BillModel.tenant_id == tenant_id, BillModel.table_id == table_id, BillModel.closed_at.is_(None)
            )
        )
        return _bill(model) if model is not None else None

    async def list_open(self, tenant_id: uuid.UUID) -> list[Bill]:
        models = await self._session.scalars(
            select(BillModel).where(BillModel.tenant_id == tenant_id, BillModel.closed_at.is_(None))
        )
        return [_bill(model) for model in models]

    async def update(self, bill: Bill) -> None:
        await self._session.execute(
            update(BillModel)
            .where(BillModel.tenant_id == bill.tenant_id, BillModel.id == bill.id)
            .values(
                closed_at=bill.closed_at,
                payment_method=bill.payment_method.value if bill.payment_method else None,
                paid_cents=bill.paid_cents,
            )
        )


def _guest(model: GuestModel) -> Guest:
    return Guest(
        id=model.id,
        tenant_id=model.tenant_id,
        table_id=model.table_id,
        bill_id=model.bill_id,
        name=model.name,
        joined_at=model.joined_at,
        ended_at=model.ended_at,
    )


class SqlAlchemyGuestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, guest: Guest) -> None:
        self._session.add(
            GuestModel(
                id=guest.id,
                tenant_id=guest.tenant_id,
                table_id=guest.table_id,
                bill_id=guest.bill_id,
                name=guest.name,
                joined_at=guest.joined_at,
            )
        )
        await self._session.flush()

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        model = await self._session.scalar(
            select(GuestModel).where(GuestModel.tenant_id == tenant_id, GuestModel.id == guest_id)
        )
        return _guest(model) if model is not None else None

    async def count_for_bill(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(GuestModel)
            .where(GuestModel.tenant_id == tenant_id, GuestModel.bill_id == bill_id)
        )
        return int(count or 0)

    async def end_all_for_table(self, tenant_id: uuid.UUID, table_id: uuid.UUID, at: datetime) -> list[uuid.UUID]:
        result = await self._session.execute(
            update(GuestModel)
            .where(GuestModel.tenant_id == tenant_id, GuestModel.table_id == table_id, GuestModel.ended_at.is_(None))
            .values(ended_at=at)
            .returning(GuestModel.id)
        )
        return list(result.scalars())


def _line(model: CartLineModel) -> CartLine:
    return CartLine(
        id=model.id,
        tenant_id=model.tenant_id,
        table_id=model.table_id,
        item_id=model.item_id,
        item_name=model.item_name,
        quantity=model.quantity,
        note=model.note,
        added_by=model.added_by,
        created_at=model.created_at,
    )


class SqlAlchemyCartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Cart:
        version = await self._session.scalar(
            select(CartModel.version).where(CartModel.tenant_id == tenant_id, CartModel.table_id == table_id)
        )
        lines = await self._session.scalars(
            select(CartLineModel)
            .where(CartLineModel.tenant_id == tenant_id, CartLineModel.table_id == table_id)
            .order_by(CartLineModel.created_at, CartLineModel.id)
        )
        return Cart(
            tenant_id=tenant_id, table_id=table_id, version=version or 0, lines=tuple(_line(line) for line in lines)
        )

    async def get_line(self, tenant_id: uuid.UUID, line_id: uuid.UUID) -> CartLine | None:
        model = await self._session.scalar(
            select(CartLineModel).where(CartLineModel.tenant_id == tenant_id, CartLineModel.id == line_id)
        )
        return _line(model) if model is not None else None

    async def line_exists_anywhere(self, line_id: uuid.UUID) -> bool:
        """In any cart or already sent in any order (an order item keeps its line's id)."""
        found = await self._session.scalar(
            select(
                exists().where(CartLineModel.id == line_id) | exists().where(OrderItemModel.id == line_id)
            )
        )
        return bool(found)

    async def add_line(self, line: CartLine) -> None:
        self._session.add(
            CartLineModel(
                id=line.id,
                tenant_id=line.tenant_id,
                table_id=line.table_id,
                item_id=line.item_id,
                item_name=line.item_name,
                quantity=line.quantity,
                note=line.note,
                added_by=line.added_by,
                created_at=line.created_at,
            )
        )
        await self._session.flush()

    async def update_line(self, line: CartLine) -> None:
        await self._session.execute(
            update(CartLineModel)
            .where(CartLineModel.tenant_id == line.tenant_id, CartLineModel.id == line.id)
            .values(quantity=line.quantity, note=line.note)
        )

    async def delete_line(self, tenant_id: uuid.UUID, line_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(CartLineModel).where(CartLineModel.tenant_id == tenant_id, CartLineModel.id == line_id)
        )

    async def clear(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(CartLineModel).where(CartLineModel.tenant_id == tenant_id, CartLineModel.table_id == table_id)
        )

    async def bump_version(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> int:
        statement = (
            insert(CartModel)
            .values(id=uuid.uuid4(), tenant_id=tenant_id, table_id=table_id, version=1)
            .on_conflict_do_update(index_elements=[CartModel.table_id], set_={"version": CartModel.version + 1})
            .returning(CartModel.version)
        )
        version = await self._session.scalar(statement)
        return int(version or 0)


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> None:
        self._session.add(
            OrderModel(
                id=order.id,
                tenant_id=order.tenant_id,
                table_id=order.table_id,
                bill_id=order.bill_id,
                number=order.number,
                sent_by=order.sent_by,
                created_at=order.created_at,
            )
        )
        await self._session.flush()
        self._session.add_all(
            OrderItemModel(
                id=item.id,
                tenant_id=order.tenant_id,
                order_id=order.id,
                item_id=item.item_id,
                name=item.name,
                unit_price_cents=item.unit_price_cents,
                quantity=item.quantity,
                note=item.note,
                added_by=item.added_by,
                status=item.status.value,
                position=position,
            )
            for position, item in enumerate(order.items)
        )
        await self._session.flush()

    async def _orders(self, tenant_id: uuid.UUID, *conditions: object) -> list[Order]:
        models = list(
            await self._session.scalars(
                select(OrderModel)
                .where(OrderModel.tenant_id == tenant_id, *conditions)  # type: ignore[arg-type]
                .order_by(OrderModel.number)
            )
        )
        if not models:
            return []
        items: dict[uuid.UUID, list[OrderItem]] = {}
        for item in await self._session.scalars(
            select(OrderItemModel)
            .where(OrderItemModel.tenant_id == tenant_id, OrderItemModel.order_id.in_([m.id for m in models]))
            .order_by(OrderItemModel.position)
        ):
            items.setdefault(item.order_id, []).append(
                OrderItem(
                    id=item.id,
                    item_id=item.item_id,
                    name=item.name,
                    unit_price_cents=item.unit_price_cents,
                    quantity=item.quantity,
                    note=item.note,
                    added_by=item.added_by,
                    status=OrderItemStatus(item.status),
                )
            )
        return [
            Order(
                id=model.id,
                tenant_id=model.tenant_id,
                table_id=model.table_id,
                bill_id=model.bill_id,
                number=model.number,
                sent_by=model.sent_by,
                created_at=model.created_at,
                items=tuple(items.get(model.id, [])),
            )
            for model in models
        ]

    async def get(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        orders = await self._orders(tenant_id, OrderModel.id == order_id)
        return orders[0] if orders else None

    async def exists_anywhere(self, order_id: uuid.UUID) -> bool:
        return bool(await self._session.scalar(select(exists().where(OrderModel.id == order_id))))

    async def list_for_bill(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> list[Order]:
        return await self._orders(tenant_id, OrderModel.bill_id == bill_id)

    async def next_number(self, tenant_id: uuid.UUID) -> int:
        statement = (
            insert(OrderCounterModel)
            .values(tenant_id=tenant_id, last_number=1)
            .on_conflict_do_update(
                index_elements=[OrderCounterModel.tenant_id], set_={"last_number": OrderCounterModel.last_number + 1}
            )
            .returning(OrderCounterModel.last_number)
        )
        return int(await self._session.scalar(statement) or 0)
