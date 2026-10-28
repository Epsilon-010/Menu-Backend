import uuid
from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.bills import (
    BillDetail,
    CloseTable,
    GetBill,
    ListTables,
    OpenTable,
    PayBill,
    TableOverview,
)
from app.modules.orders.application.ordering import (
    AddCartLine,
    CartView,
    GetCart,
    ListTableOrders,
    Ordering,
    RemoveCartLine,
    SubmitCart,
    UpdateCartLine,
)
from app.modules.orders.domain.errors import (
    BillHasOrders,
    BillNotFound,
    CartChanged,
    CartEmpty,
    CartFull,
    CartLineNotFound,
    DinerNotAllowed,
    InvalidOrderData,
    ItemsUnavailable,
    OrderIdTaken,
    TableNotFound,
)
from app.modules.orders.domain.model import (
    MAX_NOTE_LENGTH,
    MAX_QUANTITY,
    Diner,
    Order,
    OrderItemStatus,
    OrderStatus,
    PaymentMethod,
)
from app.modules.orders.infrastructure.adapters import CatalogMenu, RedisTableEvents, TablesModule
from app.modules.orders.infrastructure.guest_sessions import RevokedGuestAccess
from app.modules.orders.infrastructure.repository import (
    PostgresTableLocks,
    SqlAlchemyBillRepository,
    SqlAlchemyCartRepository,
    SqlAlchemyGuestRepository,
    SqlAlchemyOrderRepository,
)
from app.shared.domain.principal import Principal, Role
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import require_role
from app.shared.infrastructure.http.problems import problem
from app.shared.infrastructure.security import SystemClock

table_router = APIRouter(prefix="/table", tags=["table"])
bills_router = APIRouter(prefix="/bills", tags=["bills"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Staff = Annotated[Principal, Depends(require_role("admin", "waiter"))]
T = TypeVar("T")


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


# --- Schemas -----------------------------------------------------------------------------------


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CartLineIn(_In):
    # Optional client-chosen id: repeating the add never adds the line twice.
    id: uuid.UUID | None = None
    item_id: uuid.UUID
    quantity: int = Field(default=1, strict=True, ge=1, le=MAX_QUANTITY)
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)


class CartLineUpdate(_In):
    quantity: int | None = Field(default=None, strict=True, ge=1, le=MAX_QUANTITY)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


class SubmitIn(_In):
    id: uuid.UUID | None = None
    # The cart version the sender reviewed and confirmed.
    cart_version: int = Field(strict=True, ge=0)


class OpenTableIn(_In):
    table_id: uuid.UUID


class PaymentIn(_In):
    method: PaymentMethod


class CartLineOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    name: str
    quantity: int
    note: str
    added_by: str
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


class BillOut(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    table_name: str
    opened_at: datetime
    closed_at: datetime | None
    payment_method: PaymentMethod | None
    orders: list[OrderOut]
    total_cents: int


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
                unit_price_cents=item.unit_price_cents,
                subtotal_cents=item.subtotal_cents,
            )
            for item in order.items
        ],
        total_cents=order.total_cents,
    )


def _bill_out(detail: BillDetail) -> BillOut:
    return BillOut(
        id=detail.bill.id,
        table_id=detail.bill.table_id,
        table_name=detail.table_name,
        opened_at=detail.bill.opened_at,
        closed_at=detail.bill.closed_at,
        payment_method=detail.bill.payment_method,
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
    except BillHasOrders:
        return problem(status.HTTP_409_CONFLICT, "A bill with orders is closed by registering its payment")
    except CartLineNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Cart line not found")
    except TableNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Table not found")
    except BillNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Bill not found")


# --- Table routes: the tablet and the guests of its open visit ---------------------------------


@table_router.get("/cart", response_model=CartOut)
async def read_cart(diner: DinerDep, ctx: OrderingDep) -> CartOut | JSONResponse:
    result = await _run(GetCart(ctx).execute(diner))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.post("/cart/lines", response_model=CartOut)
async def add_cart_line(body: CartLineIn, diner: DinerDep, ctx: OrderingDep) -> CartOut | JSONResponse:
    result = await _run(AddCartLine(ctx).execute(diner, body.item_id, body.quantity, body.note, body.id))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.patch("/cart/lines/{line_id}", response_model=CartOut)
async def update_cart_line(
    line_id: uuid.UUID, body: CartLineUpdate, diner: DinerDep, ctx: OrderingDep
) -> CartOut | JSONResponse:
    result = await _run(UpdateCartLine(ctx).execute(diner, line_id, body.quantity, body.note))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.delete("/cart/lines/{line_id}", response_model=CartOut)
async def remove_cart_line(line_id: uuid.UUID, diner: DinerDep, ctx: OrderingDep) -> CartOut | JSONResponse:
    result = await _run(RemoveCartLine(ctx).execute(diner, line_id))
    return result if isinstance(result, JSONResponse) else _cart_out(result)


@table_router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def submit_order(body: SubmitIn, diner: DinerDep, ctx: OrderingDep) -> OrderOut | JSONResponse:
    result = await _run(SubmitCart(ctx).execute(diner, body.cart_version, body.id))
    return result if isinstance(result, JSONResponse) else _order_out(result)


@table_router.get("/orders", response_model=list[OrderOut])
async def list_table_orders(diner: DinerDep, ctx: OrderingDep) -> list[OrderOut] | JSONResponse:
    result = await _run(ListTableOrders(ctx).execute(diner))
    return result if isinstance(result, JSONResponse) else [_order_out(order) for order in result]


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


@bills_router.post("/{bill_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_table(bill_id: uuid.UUID, staff: Staff, ctx: OrderingDep) -> Response:
    result = await _run(CloseTable(ctx).execute(staff.tenant_id, bill_id))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)
