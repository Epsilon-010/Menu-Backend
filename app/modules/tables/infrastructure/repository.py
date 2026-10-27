import secrets
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tables.domain.table import PIN_LENGTH, TABLE_CODE_ALPHABET, TABLE_CODE_LENGTH, Table
from app.modules.tables.infrastructure.models import TableModel


class RandomTableCredentials:
    """Codes and PINs from the OS CSPRNG."""

    def new_code(self) -> str:
        return "".join(secrets.choice(TABLE_CODE_ALPHABET) for _ in range(TABLE_CODE_LENGTH))

    def new_pin(self) -> str:
        return "".join(secrets.choice("0123456789") for _ in range(PIN_LENGTH))


def _to_entity(model: TableModel) -> Table:
    return Table(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        code=model.code,
        pin_hash=model.pin_hash,
        is_active=model.is_active,
    )


class SqlAlchemyTableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, table: Table) -> None:
        self._session.add(
            TableModel(
                id=table.id,
                tenant_id=table.tenant_id,
                name=table.name,
                code=table.code,
                pin_hash=table.pin_hash,
                is_active=table.is_active,
            )
        )
        await self._session.flush()

    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None:
        model = await self._session.scalar(
            select(TableModel).where(TableModel.tenant_id == tenant_id, TableModel.id == table_id)
        )
        return _to_entity(model) if model is not None else None

    async def get_by_code(self, code: str) -> Table | None:
        # The only query without a tenant filter: the device login runs before any tenant is known.
        model = await self._session.scalar(select(TableModel).where(TableModel.code == code))
        return _to_entity(model) if model is not None else None

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Table | None:
        model = await self._session.scalar(
            select(TableModel).where(TableModel.tenant_id == tenant_id, func.lower(TableModel.name) == name.lower())
        )
        return _to_entity(model) if model is not None else None

    async def list(self, tenant_id: uuid.UUID) -> list[Table]:
        models = await self._session.scalars(
            select(TableModel).where(TableModel.tenant_id == tenant_id).order_by(func.lower(TableModel.name))
        )
        return [_to_entity(model) for model in models]

    async def update(self, table: Table) -> None:
        # Tenant-scoped like every other query; the code never changes.
        await self._session.execute(
            update(TableModel)
            .where(TableModel.tenant_id == table.tenant_id, TableModel.id == table.id)
            .values(name=table.name, pin_hash=table.pin_hash, is_active=table.is_active)
        )
