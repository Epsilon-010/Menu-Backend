"""Admin use cases over the tenant's tables.

Every lookup is scoped to the admin's tenant: another tenant's tables are reported as not
found. There is no hard delete; deactivating is the removal.
"""

import uuid
from dataclasses import dataclass, replace

from app.modules.tables.domain.errors import TableNameNotAvailable, TableNotFound
from app.modules.tables.domain.table import (
    SessionRevoker,
    Table,
    TableCredentials,
    TableRepository,
    validate_table_name,
)
from app.shared.domain.ports import PasswordHasher, UnitOfWork

# Codes come from ~887 million combinations; a collision is rare, several in a row are a bug.
_MAX_CODE_ATTEMPTS = 10


@dataclass(frozen=True)
class TableWithPin:
    """The plain PIN only exists in this result: it is shown once and stored as a hash."""

    table: Table
    pin: str


async def _get_table(tables: TableRepository, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table:
    table = await tables.get(tenant_id, table_id)
    if table is None:
        raise TableNotFound(table_id)
    return table


async def _ensure_name_available(
    tables: TableRepository, tenant_id: uuid.UUID, name: str, table_id: uuid.UUID | None = None
) -> None:
    existing = await tables.get_by_name(tenant_id, name)
    if existing is not None and existing.id != table_id:
        raise TableNameNotAvailable(name)


class CreateTable:
    def __init__(
        self, tables: TableRepository, credentials: TableCredentials, hasher: PasswordHasher, uow: UnitOfWork
    ) -> None:
        self._tables = tables
        self._credentials = credentials
        self._hasher = hasher
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, name: str) -> TableWithPin:
        name = validate_table_name(name)
        await _ensure_name_available(self._tables, tenant_id, name)

        pin = self._credentials.new_pin()
        table = Table.create(tenant_id, name, await self._unused_code(), await self._hasher.hash(pin))
        await self._tables.add(table)
        await self._uow.commit()
        return TableWithPin(table=table, pin=pin)

    async def _unused_code(self) -> str:
        for _ in range(_MAX_CODE_ATTEMPTS):
            code = self._credentials.new_code()
            if await self._tables.get_by_code(code) is None:
                return code
        raise RuntimeError("Could not generate an unused table code")


class ListTables:
    def __init__(self, tables: TableRepository) -> None:
        self._tables = tables

    async def execute(self, tenant_id: uuid.UUID) -> list[Table]:
        return await self._tables.list(tenant_id)


class UpdateTable:
    """Renames or (de)activates. Deactivating ends every session of the table's device right away."""

    def __init__(self, tables: TableRepository, sessions: SessionRevoker, uow: UnitOfWork) -> None:
        self._tables = tables
        self._sessions = sessions
        self._uow = uow

    async def execute(
        self, tenant_id: uuid.UUID, table_id: uuid.UUID, name: str | None = None, is_active: bool | None = None
    ) -> Table:
        table = await _get_table(self._tables, tenant_id, table_id)
        updated = table.with_changes(name=name, is_active=is_active)
        if updated.name != table.name:
            await _ensure_name_available(self._tables, tenant_id, updated.name, table_id)

        await self._tables.update(updated)
        if table.is_active and not updated.is_active:
            await self._sessions.revoke_all(tenant_id, table_id)
        await self._uow.commit()
        return updated


class RegenerateTablePin:
    """Issues a new PIN (the code stays) and signs the table's device out."""

    def __init__(
        self,
        tables: TableRepository,
        credentials: TableCredentials,
        hasher: PasswordHasher,
        sessions: SessionRevoker,
        uow: UnitOfWork,
    ) -> None:
        self._tables = tables
        self._credentials = credentials
        self._hasher = hasher
        self._sessions = sessions
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> TableWithPin:
        table = await _get_table(self._tables, tenant_id, table_id)
        pin = self._credentials.new_pin()
        updated = replace(table, pin_hash=await self._hasher.hash(pin))

        await self._tables.update(updated)
        await self._sessions.revoke_all(tenant_id, table_id)
        await self._uow.commit()
        return TableWithPin(table=updated, pin=pin)
