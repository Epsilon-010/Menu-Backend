"""What other modules use to end the visits of a table's guests, without knowing how orders stores them."""

import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.guests import EndTableGuests
from app.modules.orders.infrastructure.repository import PostgresTableLocks, SqlAlchemyGuestRepository
from app.shared.domain.principal import AccessRevocations
from app.shared.infrastructure.security import SystemClock

# Guests' access tokens carry session version 1; ending a visit requires 2 from then on.
_ENDED_GUEST_VERSION = 2


class RevokedGuestAccess:
    def __init__(self, revocations: AccessRevocations) -> None:
        self._revocations = revocations

    async def end_access(self, guest_ids: list[uuid.UUID]) -> None:
        for guest_id in guest_ids:
            await self._revocations.require_version(guest_id, _ENDED_GUEST_VERSION)


class TableGuestSessions:
    """Adapter of the tables `TableGuests` port: ends in the caller's transaction, revokes after its commit."""

    def __init__(self, end_guests: EndTableGuests, access: RevokedGuestAccess) -> None:
        self._end_guests = end_guests
        self._access = access
        self._ended: list[uuid.UUID] = []

    async def end_all(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        self._ended += await self._end_guests.execute(tenant_id, table_id)

    async def end_access(self) -> None:
        await self._access.end_access(self._ended)
        self._ended = []


def table_guest_sessions(request: Request, session: AsyncSession) -> TableGuestSessions:
    """Runs in the caller's transaction (`session`); the caller commits."""
    return TableGuestSessions(
        EndTableGuests(PostgresTableLocks(session), SqlAlchemyGuestRepository(session), SystemClock()),
        RevokedGuestAccess(request.app.state.access_revocations),
    )
