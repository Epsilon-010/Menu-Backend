import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.orders.domain.model import Bill, Cart, CartLine, Guest, Order, OrderItemStatus


class TableLocks(Protocol):
    async def lock(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        """Serializes everything that touches one table's bill, guests, cart and orders until the
        transaction ends: one lock per table, taken first, so these use cases never deadlock."""
        ...


class BillRepository(Protocol):
    async def add(self, bill: Bill) -> None: ...

    async def get(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill | None: ...

    async def get_open(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Bill | None: ...

    async def list_open(self, tenant_id: uuid.UUID) -> list[Bill]: ...

    async def update(self, bill: Bill) -> None: ...


class GuestRepository(Protocol):
    async def add(self, guest: Guest) -> None: ...

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None: ...

    async def count_for_bill(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> int: ...

    async def end_all_for_table(self, tenant_id: uuid.UUID, table_id: uuid.UUID, at: datetime) -> list[uuid.UUID]:
        """Ends every active guest of the table; returns their ids."""
        ...


class CartRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Cart:
        """The table's cart (version 0 and no lines when it never had one)."""
        ...

    async def get_line(self, tenant_id: uuid.UUID, line_id: uuid.UUID) -> CartLine | None: ...

    async def line_exists_anywhere(self, line_id: uuid.UUID) -> bool: ...

    async def line_sent_on_bill(self, tenant_id: uuid.UUID, bill_id: uuid.UUID, line_id: uuid.UUID) -> bool:
        """Whether the line was already sent in an order of this bill (the order item keeps its id)."""
        ...

    async def add_line(self, line: CartLine) -> None: ...

    async def update_line(self, line: CartLine) -> None: ...

    async def delete_line(self, tenant_id: uuid.UUID, line_id: uuid.UUID) -> None: ...

    async def clear(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None: ...

    async def bump_version(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> int:
        """Moves the cart to its next version (creating it at 1) and returns it."""
        ...


@dataclass(frozen=True)
class DishChange:
    """Moves some dishes of one order to `target`, only from `sources`; who did it and when go to the history."""

    item_ids: frozenset[uuid.UUID]
    sources: frozenset[OrderItemStatus]
    target: OrderItemStatus
    changed_by: uuid.UUID
    at: datetime
    reason: str | None = None


class OrderRepository(Protocol):
    async def add(self, order: Order) -> None: ...

    async def get(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> Order | None: ...

    async def exists_anywhere(self, order_id: uuid.UUID) -> bool: ...

    async def list_for_bill(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> list[Order]:
        """Oldest first."""
        ...

    async def next_number(self, tenant_id: uuid.UUID) -> int:
        """The tenant's next display number, assigned atomically."""
        ...

    async def list_with_dishes_in(self, tenant_id: uuid.UUID, statuses: frozenset[OrderItemStatus]) -> list[Order]:
        """Orders with at least one dish in one of `statuses` (with all their dishes), by number."""
        ...

    async def change_dishes(self, tenant_id: uuid.UUID, order_id: uuid.UUID, change: DishChange) -> bool:
        """Applies the change to every dish or to none: one conditional update on the expected states.
        Returns False (changing nothing) when any dish is not in `change.sources`."""
        ...


class OrderSettingsRepository(Protocol):
    async def late_order_minutes(self, tenant_id: uuid.UUID) -> int:
        """The tenant's threshold, or the default when it never set one."""
        ...

    async def set_late_order_minutes(self, tenant_id: uuid.UUID, minutes: int) -> None: ...


@dataclass(frozen=True)
class MenuItem:
    item_id: uuid.UUID
    name: str
    price_cents: int


class Menu(Protocol):
    """Port to the catalog: what can be ordered right now, at the current price."""

    async def orderable(self, tenant_id: uuid.UUID, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, MenuItem]: ...


@dataclass(frozen=True)
class TableInfo:
    name: str
    is_active: bool
    session_version: int
    qr_token: str | None = None


class Tables(Protocol):
    """Port to the tables module."""

    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> TableInfo | None: ...

    async def list_active(self, tenant_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
        """(id, name) of the tenant's active tables, by name."""
        ...


class GuestAccess(Protocol):
    """Port to auth: rejects the live access tokens of guests whose visit ended. Call it after the commit."""

    async def end_access(self, guest_ids: list[uuid.UUID]) -> None: ...


class TableEvents(Protocol):
    """Port: tells everyone at a table (and staff) that something changed. Call it after the commit;
    a lost event only delays the update until the next poll."""

    async def publish(
        self,
        tenant_id: uuid.UUID,
        table_id: uuid.UUID,
        kind: str,
        cart_version: int | None = None,
        order_id: uuid.UUID | None = None,
    ) -> None: ...
