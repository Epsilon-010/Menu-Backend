import uuid

from app.modules.tables.domain.table import Table, TableRepository, normalize_table_code


class FindTableByCode:
    """Platform-wide lookup used only by the device login, before any tenant is known."""

    def __init__(self, tables: TableRepository) -> None:
        self._tables = tables

    async def execute(self, code: str) -> Table | None:
        return await self._tables.get_by_code(normalize_table_code(code))


class GetTable:
    def __init__(self, tables: TableRepository) -> None:
        self._tables = tables

    async def execute(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None:
        return await self._tables.get(tenant_id, table_id)
