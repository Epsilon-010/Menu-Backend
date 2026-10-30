import re
import uuid
from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.bills import (
    BillDetail,
    CloseTable,
    DismissBillRequest,
    GetBill,
    ListTables,
    OpenTable,
    PayBill,
    TableOverview,
)
from app.modules.orders.application.kitchen import (
    AddDishToOrder,
    ChangeDishStatus,
    GetOrderSettings,
    Kitchen,
    ListDeliveries,
    ListKitchenOrders,
    StaffMember,
    StaffOrder,
    UpdateOrderSettings,
)
from app.modules.orders.application.ordering import (
    AddCartLine,
    CancelBillRequest,
    CartView,
    GetBillRequest,
    GetCart,
    ListTableOrders,
    Ordering,
    RemoveCartLine,
    RequestBill,
    SubmitCart,
    UpdateCartLine,
    authorize,
)
from app.modules.orders.domain.errors import (
    BillClosed,
    BillHasOrders,
    BillNotFound,
    CartChanged,
    CartEmpty,
    CartFull,
    CartLineNotFound,
    DinerNotAllowed,
    DishesChanged,
    DishesNotInOrder,
    InvalidOrderData,
    ItemsUnavailable,
    NothingToPay,
    OrderIdTaken,
    OrderNotFound,
    TableNotFound,
    TransitionNotAllowed,
)
from app.modules.orders.domain.modifiers import MAX_CHOSEN_OPTIONS
from app.modules.orders.domain.model import (
    MAX_LATE_ORDER_MINUTES,
    MAX_NOTE_LENGTH,
    MAX_QUANTITY,
    MAX_REASON_LENGTH,
    Diner,
    Order,
    OrderItemStatus,
    OrderStatus,
    PaymentMethod,
)
from app.modules.orders.infrastructure.adapters import CatalogMenu, RedisTableEvents, TablesModule
from app.modules.orders.infrastructure.events import staff_events, table_events
from app.modules.orders.infrastructure.guest_sessions import RevokedGuestAccess
from app.modules.orders.infrastructure.repository import (
    PostgresTableLocks,
    SqlAlchemyBillRepository,
    SqlAlchemyCartRepository,
    SqlAlchemyGuestRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderSettingsRepository,
)
from app.shared.domain.principal import Principal, Role
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import require_role
from app.shared.infrastructure.http.problems import problem
from app.shared.infrastructure.security import SystemClock

table_router = APIRouter(prefix="/table", tags=["table"])
bills_router = APIRouter(prefix="/bills", tags=["bills"])
# The kitchen and delivery queues, dish status changes and the order settings.
staff_router = APIRouter(tags=["kitchen"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Staff = Annotated[Principal, Depends(require_role("admin", "waiter"))]
AnyStaff = Annotated[Principal, Depends(require_role("admin", "waiter", "kitchen"))]
KitchenStaff = Annotated[Principal, Depends(require_role("admin", "kitchen"))]
Admin = Annotated[Principal, Depends(require_role("admin"))]
T = TypeVar("T")
# Redis stream ids ("<ms>-<seq>"): anything else in Last-Event-ID starts from now.
_STREAM_ID = re.compile(r"\d{1,20}-\d{1,20}")


def _diner(principal: Annotated[Principal, Depends(require_role("table", "guest"))]) -> Diner:
    """The tablet or guest acting, always from the access token: tenant, table and visit never come from the request."""
    if principal.table_id is None:  # the token decoder already requires it for both roles
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if principal.role is Role.GUEST:
        return Diner(
            tenant_id=principal.tenant_id,
            table_id=principal.table_id,
            guest_id=principal.subject_id,
            bill_id=principal.bill_id,
        )
    return Diner(tenant_id=principal.tenant_id, table_id=principal.table_id, session_version=principal.session_version)


DinerDep = Annotated[Diner, Depends(_diner)]


def get_ordering(request: Request, session: SessionDep) -> Ordering:
    return Ordering(
        locks=PostgresTableLocks(session),
        bills=SqlAlchemyBillRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        carts=SqlAlchemyCartRepository(session),
        orders=SqlAlchemyOrderRepository(session),
        menu=CatalogMenu(session),
        tables=TablesModule(session),
        guest_access=RevokedGuestAccess(request.app.state.access_revocations),
        events=RedisTableEvents(request.app.state.redis),
        clock=SystemClock(),
        uow=SqlAlchemyUnitOfWork(session),
    )


OrderingDep = Annotated[Ordering, Depends(get_ordering)]


def get_kitchen(request: Request, session: SessionDep) -> Kitchen:
    return Kitchen(
        locks=PostgresTableLocks(session),
        bills=SqlAlchemyBillRepository(session),
        orders=SqlAlchemyOrderRepository(session),
        menu=CatalogMenu(session),
        settings=SqlAlchemyOrderSettingsRepository(session),
        tables=TablesModule(session),
        events=RedisTableEvents(request.app.state.redis),
        clock=SystemClock(),
        uow=SqlAlchemyUnitOfWork(session),
    )


KitchenDep = Annotated[Kitchen, Depends(get_kitchen)]


# --- Schemas -----------------------------------------------------------------------------------


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CartLineIn(_In):
    # Optional client-chosen id: repeating the add never adds the line twice.
    id: uuid.UUID | None = None
    item_id: uuid.UUID
    quantity: int = Field(default=1, strict=True, ge=1, le=MAX_QUANTITY)
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)
    # Repeats are refused by the selection rules (each option once); the bound only stops huge bodies.
    modifier_option_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_CHOSEN_OPTIONS)


class CartLineUpdate(_In):
    quantity: int | None = Field(default=None, strict=True, ge=1, le=MAX_QUANTITY)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    # Replaces the whole selection when sent.
    modifier_option_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_CHOSEN_OPTIONS)


class SubmitIn(_In):
    id: uuid.UUID | None = None
    # The cart version the sender reviewed and confirmed.
    cart_version: int = Field(strict=True, ge=0)


class OpenTableIn(_In):
    table_id: uuid.UUID


class PaymentIn(_In):
    method: PaymentMethod


class CartModifierOut(BaseModel):
    option_id: uuid.UUID
    group: str
    name: str
    price_cents: int


class OrderModifierOut(BaseModel):
    group: str
    name: str
    price_cents: int


class StaffModifierOut(BaseModel):
    """What the kitchen and delivery queues show of an option: never its price."""

    group: str
    name: str


class CartLineOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    name: str
    quantity: int
    note: str
    added_by: str
    modifiers: list[CartModifierOut]
    available: bool
    unit_price_cents: int | None
    subtotal_cents: int


class CartOut(BaseModel):
    version: int
    lines: list[CartLineOut]
    total_cents: int


class OrderItemOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    name: str
    quantity: int
    note: str
    added_by: str
    status: OrderItemStatus
    cancel_reason: str | None
    modifiers: list[OrderModifierOut]
    # Includes the options' prices.
    unit_price_cents: int
    subtotal_cents: int


class OrderOut(BaseModel):
    id: uuid.UUID
    number: int
    status: OrderStatus
    sent_by: str
    created_at: datetime
    items: list[OrderItemOut]
    total_cents: int


class DishStatusIn(_In):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    status: Literal["preparing", "ready", "delivered", "cancelled"]
    # Required to cancel, refused for anything else (checked by the use case).
    reason: str | None = Field(default=None, min_length=1, max_length=MAX_REASON_LENGTH)

    @field_validator("item_ids")
    @classmethod
    def _unique(cls, item_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("Each dish can appear only once")
        return item_ids


class OrderDishIn(_In):
    # Optional client-chosen id: repeating the add never adds the dish twice.
    id: uuid.UUID | None = None
    item_id: uuid.UUID
    quantity: int = Field(default=1, strict=True, ge=1, le=MAX_QUANTITY)
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)
    modifier_option_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_CHOSEN_OPTIONS)


class OrderSettingsIn(_In):
    late_order_minutes: int = Field(strict=True, ge=1, le=MAX_LATE_ORDER_MINUTES)


class OrderSettingsOut(BaseModel):
    late_order_minutes: int


class StaffOrderItemOut(BaseModel):
    """A dish as the staff queues show it: never with prices."""

    id: uuid.UUID
    name: str
    quantity: int
    note: str
    added_by: str
    modifiers: list[StaffModifierOut]
    status: OrderItemStatus
    cancel_reason: str | None
    ready_at: datetime | None
    updated_at: datetime


class StaffOrderOut(BaseModel):
    id: uuid.UUID
    number: int
    table_id: uuid.UUID
    table_name: str
    sent_by: str
    created_at: datetime
    status: OrderStatus
    items: list[StaffOrderItemOut]


class BillOut(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    table_name: str
    opened_at: datetime
    closed_at: datetime | None
    payment_method: PaymentMethod | None
    # When the table asked for the bill and nobody attended it yet.
    bill_requested_at: datetime | None
    orders: list[OrderOut]
    total_cents: int


class BillRequestOut(BaseModel):
    requested_at: datetime | None


class TableOverviewOut(BaseModel):
    table_id: uuid.UUID
    table_name: str
    bill: BillOut | None


def _cart_out(cart: CartView) -> CartOut:
    return CartOut(
        version=cart.version,
        lines=[
            CartLineOut(
                id=view.line.id,
                item_id=view.line.item_id,
                name=view.line.item_name,
                quantity=view.line.quantity,
                note=view.line.note,
                added_by=view.line.added_by,
                modifiers=[
                    CartModifierOut(option_id=m.option_id, group=m.group, name=m.name, price_cents=m.price_cents)
                    for m in view.modifiers
                ],
                available=view.available,
                unit_price_cents=view.unit_price_cents,
                subtotal_cents=view.subtotal_cents,
            )
            for view in cart.lines
        ],
        total_cents=cart.total_cents,
    )


def _order_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        number=order.number,
        status=order.status,
        sent_by=order.sent_by,
        created_at=order.created_at,
        items=[
            OrderItemOut(
                id=item.id,
                item_id=item.item_id,
                name=item.name,
                quantity=item.quantity,
                note=item.note,
                added_by=item.added_by,
                status=item.status,
                cancel_reason=item.cancel_reason,
                modifiers=[OrderModifierOut(group=m.group, name=m.name, price_cents=m.price_cents) for m in item.modifiers],
                unit_price_cents=item.unit_price_cents,
                subtotal_cents=item.subtotal_cents,
            )
            for item in order.items
        ],
        total_cents=order.total_cents,
    )


def _staff_order_out(view: StaffOrder) -> StaffOrderOut:
    order = view.order
    return StaffOrderOut(
        id=order.id,
        number=order.number,
        table_id=order.table_id,
        table_name=view.table_name,
        sent_by=order.sent_by,
        created_at=order.created_at,
        status=order.status,
        items=[
            StaffOrderItemOut(
                id=item.id,
                name=item.name,
                quantity=item.quantity,
                note=item.note,
                added_by=item.added_by,
                modifiers=[StaffModifierOut(group=m.group, name=m.name) for m in item.modifiers],
                status=item.status,
                cancel_reason=item.cancel_reason,
                ready_at=item.ready_at,
                updated_at=item.updated_at or order.created_at,
            )
            for item in order.items
        ],
    )


def _bill_out(detail: BillDetail) -> BillOut:
    return BillOut(
        id=detail.bill.id,
        table_id=detail.bill.table_id,
        table_name=detail.table_name,
        opened_at=detail.bill.opened_at,
        closed_at=detail.bill.closed_at,
        payment_method=detail.bill.payment_method,
        bill_requested_at=detail.bill.bill_requested_at,
        orders=[_order_out(order) for order in detail.orders],
        total_cents=detail.total_cents,
    )


def _overview_out(overview: TableOverview) -> TableOverviewOut:
    return TableOverviewOut(
        table_id=overview.table_id,
        table_name=overview.table_name,
        bill=_bill_out(overview.bill) if overview.bill is not None else None,
    )


async def _run(call: Awaitable[T]) -> T | JSONResponse:
    """Maps the ordering errors to RFC 9457 problems."""
    try:
        return await call
    except InvalidOrderData as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except DinerNotAllowed:
        # The visit ended (bill paid, new QR) or the tablet was signed out: the client signs out too.
        return problem(status.HTTP_401_UNAUTHORIZED, "Your visit at this table has ended")
    except CartChanged:
        return problem(status.HTTP_409_CONFLICT, "The order changed, review it")
    except CartEmpty:
        return problem(status.HTTP_409_CONFLICT, "The order is empty")
    except CartFull:
        return problem(status.HTTP_409_CONFLICT, "The order is full")
    except ItemsUnavailable as error:
        return problem(
            status.HTTP_409_CONFLICT,
            "Some items are no longer available",
            unavailable_item_ids=[str(item_id) for item_id in error.args[0]],
        )
    except OrderIdTaken:
        return problem(status.HTTP_409_CONFLICT, "That id is already used by something else")
    except NothingToPay:
        return problem(status.HTTP_409_CONFLICT, "There is nothing to pay yet")
    except BillHasOrders:
        return problem(status.HTTP_409_CONFLICT, "A bill with orders is closed by registering its payment")
    except CartLineNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Cart line not found")
    except TableNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Table not found")
    except BillNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Bill not found")
    except OrderNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Order not found")
    except DishesNotInOrder:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "All dishes must belong to this order")
    except TransitionNotAllowed as error:
        return problem(status.HTTP_403_FORBIDDEN, f"Your role cannot mark dishes as {error.args[0]}")
    except DishesChanged:
        return problem(status.HTTP_409_CONFLICT, "Some dishes already changed; reload the order")
    except BillClosed:
        return problem(status.HTTP_409_CONFLICT, "This bill is already paid; its dishes can no longer change")


# --- Table routes: the tablet and the guests of its open visit ---------------------------------


@table_router.get("/cart", response_model=CartOut)
async def read_cart(diner: DinerDep, ctx: OrderingDep) -> CartOut | JSONResponse:
    result = await _run(GetCart(ctx).execute(diner))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.post("/cart/lines", response_model=CartOut)
async def add_cart_line(body: CartLineIn, diner: DinerDep, ctx: OrderingDep) -> CartOut | JSONResponse:
    result = await _run(AddCartLine(ctx).execute(
            diner, body.item_id, body.quantity, body.note, body.id, tuple(body.modifier_option_ids)
        ))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.patch("/cart/lines/{line_id}", response_model=CartOut)
async def update_cart_line(
    line_id: uuid.UUID, body: CartLineUpdate, diner: DinerDep, ctx: OrderingDep
) -> CartOut | JSONResponse:
    result = await _run(UpdateCartLine(ctx).execute(
            diner,
            line_id,
            body.quantity,
            body.note,
            None if body.modifier_option_ids is None else tuple(body.modifier_option_ids),
        ))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.delete("/cart/lines/{line_id}", response_model=CartOut)
async def remove_cart_line(line_id: uuid.UUID, diner: DinerDep, ctx: OrderingDep) -> CartOut | JSONResponse:
    result = await _run(RemoveCartLine(ctx).execute(diner, line_id))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def submit_order(body: SubmitIn, diner: DinerDep, ctx: OrderingDep) -> OrderOut | JSONResponse:
    result = await _run(SubmitCart(ctx).execute(diner, body.cart_version, body.id))
    return result if isinstance(result, JSONResponse) else _order_out(result)


@table_router.get("/events")
async def table_events_stream(
    diner: DinerDep,
    request: Request,
    last_event_id: Annotated[str | None, Header()] = None,
) -> Response:
    """SSE: `cart.updated` (with `cart_version`), `order.created`, `order.updated`, `bill.opened`,
    `bill.requested`, `bill.request_cleared` and `bill.closed` for this table.

    The visit is checked once, in a short transaction, so an open stream never holds a database connection.
    """
    async with request.app.state.session_factory() as session:
        try:
            await authorize(get_ordering(request, session), diner, lock=False)
        except DinerNotAllowed:
            return problem(status.HTTP_401_UNAUTHORIZED, "Your visit at this table has ended")
    events = table_events(
        request.app.state.redis,
        diner.tenant_id,
        diner.table_id,
        last_event_id if last_event_id and _STREAM_ID.fullmatch(last_event_id) else None,
        stop_on_close=diner.guest_id is not None,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        # Proxies (nginx) must pass each event on at once instead of buffering the response.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@table_router.get("/orders", response_model=list[OrderOut])
async def list_table_orders(diner: DinerDep, ctx: OrderingDep) -> list[OrderOut] | JSONResponse:
    result = await _run(ListTableOrders(ctx).execute(diner))
    return result if isinstance(result, JSONResponse) else [_order_out(order) for order in result]


@table_router.get("/bill-request", response_model=BillRequestOut)
async def read_bill_request(diner: DinerDep, ctx: OrderingDep) -> BillRequestOut | JSONResponse:
    result = await _run(GetBillRequest(ctx).execute(diner))
    return result if isinstance(result, JSONResponse) else BillRequestOut(requested_at=result)


@table_router.post("/bill-request", response_model=BillRequestOut)
async def request_bill(diner: DinerDep, ctx: OrderingDep) -> BillRequestOut | JSONResponse:
    """Alerts the waiters once; asking again returns the same request."""
    result = await _run(RequestBill(ctx).execute(diner))
    return result if isinstance(result, JSONResponse) else BillRequestOut(requested_at=result)


@table_router.delete("/bill-request", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_bill_request(diner: DinerDep, ctx: OrderingDep) -> Response:
    result = await _run(CancelBillRequest(ctx).execute(diner))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Bill routes: waiters and admins -----------------------------------------------------------


@bills_router.get("/tables", response_model=list[TableOverviewOut])
async def list_tables(staff: Staff, ctx: OrderingDep) -> list[TableOverviewOut]:
    return [_overview_out(overview) for overview in await ListTables(ctx).execute(staff.tenant_id)]


@bills_router.post("", response_model=BillOut)
async def open_table(body: OpenTableIn, staff: Staff, ctx: OrderingDep) -> BillOut | JSONResponse:
    result = await _run(OpenTable(ctx).execute(staff.tenant_id, body.table_id))
    return result if isinstance(result, JSONResponse) else _bill_out(result)


@bills_router.get("/{bill_id}", response_model=BillOut)
async def read_bill(bill_id: uuid.UUID, staff: Staff, ctx: OrderingDep) -> BillOut | JSONResponse:
    result = await _run(GetBill(ctx).execute(staff.tenant_id, bill_id))
    return result if isinstance(result, JSONResponse) else _bill_out(result)


@bills_router.post("/{bill_id}/payment", response_model=BillOut)
async def pay_bill(bill_id: uuid.UUID, body: PaymentIn, staff: Staff, ctx: OrderingDep) -> BillOut | JSONResponse:
    result = await _run(PayBill(ctx).execute(staff.tenant_id, bill_id, body.method))
    return result if isinstance(result, JSONResponse) else _bill_out(result)


@bills_router.delete("/{bill_id}/request", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_bill_request(bill_id: uuid.UUID, staff: Staff, ctx: OrderingDep) -> Response:
    """The waiter attends the table that asked for the bill."""
    result = await _run(DismissBillRequest(ctx).execute(staff.tenant_id, bill_id))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)


@bills_router.post("/{bill_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_table(bill_id: uuid.UUID, staff: Staff, ctx: OrderingDep) -> Response:
    result = await _run(CloseTable(ctx).execute(staff.tenant_id, bill_id))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Staff routes: the kitchen and delivery queues, dish status changes, order settings -----------


@staff_router.get("/kitchen/orders", response_model=list[StaffOrderOut])
async def kitchen_orders(staff: KitchenStaff, ctx: KitchenDep) -> list[StaffOrderOut]:
    return [_staff_order_out(view) for view in await ListKitchenOrders(ctx).execute(staff.tenant_id)]


@staff_router.get("/deliveries", response_model=list[StaffOrderOut])
async def deliveries(staff: Staff, ctx: KitchenDep) -> list[StaffOrderOut]:
    return [_staff_order_out(view) for view in await ListDeliveries(ctx).execute(staff.tenant_id)]


@staff_router.get("/orders/settings", response_model=OrderSettingsOut)
async def read_order_settings(staff: AnyStaff, ctx: KitchenDep) -> OrderSettingsOut:
    return OrderSettingsOut(late_order_minutes=await GetOrderSettings(ctx).execute(staff.tenant_id))


@staff_router.patch("/orders/settings", response_model=OrderSettingsOut)
async def update_order_settings(
    body: OrderSettingsIn, admin: Admin, ctx: KitchenDep
) -> OrderSettingsOut | JSONResponse:
    result = await _run(UpdateOrderSettings(ctx).execute(admin.tenant_id, body.late_order_minutes))
    return result if isinstance(result, JSONResponse) else OrderSettingsOut(late_order_minutes=result)


@staff_router.post("/orders/{order_id}/items/status", response_model=StaffOrderOut)
async def change_dish_status(
    order_id: uuid.UUID, body: DishStatusIn, staff: AnyStaff, ctx: KitchenDep
) -> StaffOrderOut | JSONResponse:
    """Moves dishes of one order to a status, all or nothing (see the permission matrix per role)."""
    member = StaffMember(tenant_id=staff.tenant_id, user_id=staff.subject_id, role=staff.role)
    result = await _run(
        ChangeDishStatus(ctx).execute(member, order_id, body.item_ids, OrderItemStatus(body.status), body.reason)
    )
    return result if isinstance(result, JSONResponse) else _staff_order_out(result)


@staff_router.post("/orders/{order_id}/items", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def add_order_dish(
    order_id: uuid.UUID, body: OrderDishIn, staff: Staff, ctx: KitchenDep, response: Response
) -> OrderOut | JSONResponse:
    """Adds a dish to an order of an open bill (a staff correction); 200 when it repeats an add already made."""
    result = await _run(
        AddDishToOrder(ctx).execute(
            staff.tenant_id,
            order_id,
            body.item_id,
            body.quantity,
            body.note,
            body.id,
            tuple(body.modifier_option_ids),
        )
    )
    if isinstance(result, JSONResponse):
        return result
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _order_out(result.order)


@staff_router.get("/staff/events")
async def staff_events_stream(
    staff: AnyStaff,
    request: Request,
    last_event_id: Annotated[str | None, Header()] = None,
) -> Response:
    """SSE for the kitchen, waiters and admins: `order.created`, `order.updated`, `bill.opened`,
    `bill.requested`, `bill.request_cleared` and `bill.closed` of the tenant, with `{table_id, order_id?}`;
    never cart changes or prices."""
    events = staff_events(
        request.app.state.redis,
        staff.tenant_id,
        last_event_id if last_event_id and _STREAM_ID.fullmatch(last_event_id) else None,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
