"""Guests who join a table by its QR. Used by the auth module (QR sign-in, refresh) and the tables module
(a new QR or a deactivated table ends the guests); none of these commit, the caller owns the transaction."""

import uuid

from app.modules.orders.domain.errors import TableNotOpen
from app.modules.orders.domain.model import Guest, validate_guest_name
from app.modules.orders.domain.ports import BillRepository, GuestRepository, TableLocks
from app.shared.domain.ports import Clock


class JoinTable:
    """Adds a guest to the table's open bill; raises TableNotOpen when the waiter has not opened it."""

    def __init__(self, locks: TableLocks, bills: BillRepository, guests: GuestRepository, clock: Clock) -> None:
        self._locks = locks
        self._bills = bills
        self._guests = guests
        self._clock = clock

    async def execute(self, tenant_id: uuid.UUID, table_id: uuid.UUID, name: str | None = None) -> Guest:
        name = validate_guest_name(name)
        # Same lock as paying: a guest never joins a bill that is being closed.
        await self._locks.lock(tenant_id, table_id)
        bill = await self._bills.get_open(tenant_id, table_id)
        if bill is None:
            raise TableNotOpen(table_id)
        number = await self._guests.count_for_bill(tenant_id, bill.id) + 1
        guest = Guest(
            tenant_id=tenant_id,
            table_id=table_id,
            bill_id=bill.id,
            name=name or f"Guest {number}",
            joined_at=self._clock.now(),
        )
        await self._guests.add(guest)
        return guest


class GetActiveGuest:
    """The guest while their visit lasts (not ended, within the time limit, on the table's open bill), else None."""

    def __init__(self, bills: BillRepository, guests: GuestRepository, clock: Clock) -> None:
        self._bills = bills
        self._guests = guests
        self._clock = clock

    async def execute(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        guest = await self._guests.get(tenant_id, guest_id)
        if guest is None or not guest.is_active_at(self._clock.now()):
            return None
        bill = await self._bills.get_open(tenant_id, guest.table_id)
        return guest if bill is not None and bill.id == guest.bill_id else None


class EndTableGuests:
    """Ends every guest of the table (a new QR, or the table deactivated); returns their ids so the caller
    rejects their access tokens after its commit."""

    def __init__(self, locks: TableLocks, guests: GuestRepository, clock: Clock) -> None:
        self._locks = locks
        self._guests = guests
        self._clock = clock

    async def execute(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> list[uuid.UUID]:
        await self._locks.lock(tenant_id, table_id)
        return await self._guests.end_all_for_table(tenant_id, table_id, self._clock.now())
