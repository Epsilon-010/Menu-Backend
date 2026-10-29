"""Bills (an open table), the guests who joined it by QR, the table's shared cart and the orders it sends.

They live in one module because they change together: paying a bill ends its guests and discards the
unsent cart in the same transaction, and an order is always sent on the table's open bill.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

from app.modules.orders.domain.errors import InvalidOrderData, TransitionNotAllowed
from app.shared.domain.principal import Role

MAX_QUANTITY = 50
MAX_NOTE_LENGTH = 200
MAX_CART_LINES = 100
MAX_GUEST_NAME_LENGTH = 30
MAX_REASON_LENGTH = 200
# Who a dish added by the staff to a sent order shows as added by.
STAFF_NAME = "Staff"
# Orders waiting longer than this are highlighted; each tenant may change it.
DEFAULT_LATE_ORDER_MINUTES = 15
MAX_LATE_ORDER_MINUTES = 240
# However long the table stays open, a guest's visit (and every session from it) ends after this.
GUEST_VISIT_LIMIT = timedelta(hours=12)


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"
    OTHER = "other"


@dataclass(frozen=True)
class Bill:
    """A table's visit, from opening the table (or its tablet's first order) until it is paid."""

    tenant_id: uuid.UUID
    table_id: uuid.UUID
    opened_at: datetime
    closed_at: datetime | None = None
    payment_method: PaymentMethod | None = None
    paid_cents: int | None = None
    # When someone at the table asked for the bill; cleared when they cancel or the waiter attends it.
    bill_requested_at: datetime | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def bill_requested(self, at: datetime) -> "Bill":
        return replace(self, bill_requested_at=at)

    def bill_request_cleared(self) -> "Bill":
        return replace(self, bill_requested_at=None)

    def paid(self, at: datetime, method: PaymentMethod, total_cents: int) -> "Bill":
        return replace(self, closed_at=at, payment_method=method, paid_cents=total_cents)

    def closed_without_payment(self, at: datetime) -> "Bill":
        return replace(self, closed_at=at)


def validate_guest_name(name: str | None) -> str | None:
    name = (name or "").strip()
    if len(name) > MAX_GUEST_NAME_LENGTH:
        raise InvalidOrderData(f"Name must have at most {MAX_GUEST_NAME_LENGTH} characters")
    return name or None


@dataclass(frozen=True)
class Guest:
    """Someone who scanned the table's QR while it was open. Their sessions live only as long as this
    row is active: paying or closing the bill, or a new QR, ends it."""

    tenant_id: uuid.UUID
    table_id: uuid.UUID
    bill_id: uuid.UUID
    name: str
    joined_at: datetime
    ended_at: datetime | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def ends_at(self) -> datetime:
        return self.joined_at + GUEST_VISIT_LIMIT

    def is_active_at(self, now: datetime) -> bool:
        return self.ended_at is None and now < self.ends_at


@dataclass(frozen=True)
class Diner:
    """Who acts at a table, from the access token: its tablet (`guest_id` None) or a guest."""

    tenant_id: uuid.UUID
    table_id: uuid.UUID
    guest_id: uuid.UUID | None = None
    # A guest only ever acts on the bill they joined.
    bill_id: uuid.UUID | None = None
    # The tablet's session version, checked against the table so a new PIN stops it at once.
    session_version: int = 1


def validate_quantity(quantity: int) -> int:
    if not 1 <= quantity <= MAX_QUANTITY:
        raise InvalidOrderData(f"Quantity must be between 1 and {MAX_QUANTITY}")
    return quantity


def validate_note(note: str) -> str:
    note = note.strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise InvalidOrderData(f"Note must have at most {MAX_NOTE_LENGTH} characters")
    return note


@dataclass(frozen=True)
class CartLine:
    """One line of the table's shared cart; it keeps who added it. Prices come from the menu when read."""

    tenant_id: uuid.UUID
    table_id: uuid.UUID
    item_id: uuid.UUID
    # The name when it was added, to show the line even if the item later leaves the menu.
    item_name: str
    quantity: int
    note: str
    added_by: str
    created_at: datetime
    # Sending the cart keeps this id on the order item, so a repeated add after sending adds nothing.
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def with_changes(self, quantity: int | None = None, note: str | None = None) -> "CartLine":
        return replace(
            self,
            quantity=self.quantity if quantity is None else validate_quantity(quantity),
            note=self.note if note is None else validate_note(note),
        )

    def same_request(self, item_id: uuid.UUID, quantity: int, note: str) -> bool:
        """Whether a repeated add with this line's id asks for the same thing."""
        return (self.item_id, self.quantity, self.note) == (item_id, quantity, validate_note(note))


@dataclass(frozen=True)
class Cart:
    """The table's one open cart. `version` goes up with every change, so a confirmation can prove it
    sends exactly what the sender saw."""

    tenant_id: uuid.UUID
    table_id: uuid.UUID
    version: int
    lines: tuple[CartLine, ...] = ()


class OrderItemStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    PARTIALLY_DELIVERED = "partially_delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Target status -> (the statuses a dish may move from, the roles that may move it there).
_TRANSITIONS: dict[OrderItemStatus, tuple[frozenset[OrderItemStatus], frozenset[Role]]] = {
    OrderItemStatus.PREPARING: (frozenset({OrderItemStatus.QUEUED}), frozenset({Role.ADMIN, Role.KITCHEN})),
    # A drink needs no preparation: it may go straight from queued to ready.
    OrderItemStatus.READY: (
        frozenset({OrderItemStatus.QUEUED, OrderItemStatus.PREPARING}),
        frozenset({Role.ADMIN, Role.KITCHEN}),
    ),
    OrderItemStatus.DELIVERED: (frozenset({OrderItemStatus.READY}), frozenset({Role.ADMIN, Role.WAITER})),
    # Only a dish nobody started can be cancelled (rejected by the kitchen), always with a reason.
    OrderItemStatus.CANCELLED: (
        frozenset({OrderItemStatus.QUEUED}),
        frozenset({Role.ADMIN, Role.WAITER, Role.KITCHEN}),
    ),
}


def can_transition(source: OrderItemStatus, target: OrderItemStatus) -> bool:
    return target in _TRANSITIONS and source in _TRANSITIONS[target][0]


def sources_for(target: OrderItemStatus, role: Role) -> frozenset[OrderItemStatus]:
    """The statuses `role` may move dishes from to reach `target`; raises TransitionNotAllowed otherwise."""
    if target not in _TRANSITIONS or role not in _TRANSITIONS[target][1]:
        raise TransitionNotAllowed(target)
    return _TRANSITIONS[target][0]


def validate_change_reason(target: OrderItemStatus, reason: str | None) -> str | None:
    """Cancelling needs a reason (the table and the waiters see it); no other change takes one."""
    reason = (reason or "").strip()
    if target is not OrderItemStatus.CANCELLED:
        if reason:
            raise InvalidOrderData("Only cancelled dishes take a reason")
        return None
    if not reason:
        raise InvalidOrderData("A reason is required to cancel dishes")
    if len(reason) > MAX_REASON_LENGTH:
        raise InvalidOrderData(f"The reason must have at most {MAX_REASON_LENGTH} characters")
    return reason


def validate_late_order_minutes(minutes: int) -> int:
    if not 1 <= minutes <= MAX_LATE_ORDER_MINUTES:
        raise InvalidOrderData(f"The late order threshold must be between 1 and {MAX_LATE_ORDER_MINUTES} minutes")
    return minutes


@dataclass(frozen=True)
class OrderItem:
    item_id: uuid.UUID
    name: str
    unit_price_cents: int
    quantity: int
    note: str
    added_by: str
    status: OrderItemStatus = OrderItemStatus.QUEUED
    # When it last became ready, when it last changed (None until stored) and why it was cancelled.
    ready_at: datetime | None = None
    updated_at: datetime | None = None
    cancel_reason: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def subtotal_cents(self) -> int:
        return self.unit_price_cents * self.quantity


def derive_order_status(statuses: list[OrderItemStatus]) -> OrderStatus:
    """The order status always follows from its items; it is never edited by hand."""
    live = [status for status in statuses if status is not OrderItemStatus.CANCELLED]
    if not live:
        return OrderStatus.CANCELLED
    if all(status is OrderItemStatus.DELIVERED for status in live):
        return OrderStatus.COMPLETED
    if any(status is OrderItemStatus.DELIVERED for status in live):
        return OrderStatus.PARTIALLY_DELIVERED
    if any(status in (OrderItemStatus.PREPARING, OrderItemStatus.READY) for status in live):
        return OrderStatus.IN_PROGRESS
    return OrderStatus.QUEUED


@dataclass(frozen=True)
class Order:
    """One round sent by a table: the whole cart at the moment someone confirmed it."""

    tenant_id: uuid.UUID
    table_id: uuid.UUID
    bill_id: uuid.UUID
    number: int
    created_at: datetime
    sent_by: str
    items: tuple[OrderItem, ...]
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def total_cents(self) -> int:
        """Cancelled items are never charged."""
        return sum(item.subtotal_cents for item in self.items if item.status is not OrderItemStatus.CANCELLED)

    @property
    def status(self) -> OrderStatus:
        return derive_order_status([item.status for item in self.items])
