"""Guests who join a table by its QR. Used by the auth module (QR sign-in, refresh) and the tables module
(a new QR or a deactivated table ends the guests); none of these commit, the caller owns the transaction."""

import uuid
from dataclasses import dataclass

from app.modules.orders.application.ordering import open_bill
from app.modules.orders.domain.errors import QrNotValid, TableFull
from app.modules.orders.domain.model import Guest, validate_guest_name
from app.modules.orders.domain.ports import BillRepository, GuestRepository, TableEvents, TableLocks, Tables
from app.shared.domain.ports import Clock


# Far beyond any real table, so one QR photo cannot mint endless guests (each with its own sessions
# and live-update streams).
MAX_GUESTS_PER_VISIT = 30


@dataclass(frozen=True)
class JoinedTable:
    guest: Guest
    # True when this scan opened the visit (nobody was sitting at the table): the staff hear of it.
    opened_visit: bool


class JoinTable:
    """Adds a guest to the table's open bill, opening a new one (a new visit) when the table has none;
    raises QrNotValid when the scanned QR is no longer the table's and TableFull past the guest cap."""

    def __init__(
        self,
        locks: TableLocks,
        tables: Tables,
        bills: BillRepository,
        guests: GuestRepository,
        events: TableEvents,
        clock: Clock,
    ) -> None:
        self._locks = locks
        self._tables = tables
        self._bills = bills
        self._guests = guests
        self._events = events
        self._clock = clock

    async def execute(
        self, tenant_id: uuid.UUID, table_id: uuid.UUID, qr_token: str, name: str | None = None
    ) -> JoinedTable:
        name = validate_guest_name(name)
        # Same lock as paying, opening the table, a new QR and deactivating: a guest never joins a visit
        # being ended, and two phones scanning at once open one visit, not two.
        await self._locks.lock(tenant_id, table_id)
        # Checked again under the lock: the QR may have been replaced while this scan waited for it.
        table = await self._tables.get(tenant_id, table_id)
        if table is None or not table.is_active or table.qr_token != qr_token:
            raise QrNotValid(table_id)
        bill = await self._bills.get_open(tenant_id, table_id)
        opened_visit = bill is None
        if bill is None:
            # Nobody is sitting here (or the last visit was paid): this scan starts the next visit. Guests of
            # a paid visit stay out, since their sessions are bound to that bill.
            bill = await open_bill(self._bills, tenant_id, table_id, self._clock.now())
        joined = 0 if opened_visit else await self._guests.count_for_bill(tenant_id, bill.id)
        if joined >= MAX_GUESTS_PER_VISIT:
            raise TableFull(table_id)
        number = joined + 1
        guest = Guest(
            tenant_id=tenant_id,
            table_id=table_id,
            bill_id=bill.id,
            name=name or f"Guest {number}",
            joined_at=self._clock.now(),
        )
        await self._guests.add(guest)
        return JoinedTable(guest=guest, opened_visit=opened_visit)

    async def announce(self, joined: JoinedTable) -> None:
        """Call after the commit: tells the staff (and the table) that the scan opened the table."""
        if joined.opened_visit:
            await self._events.publish(joined.guest.tenant_id, joined.guest.table_id, "bill.opened")


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
