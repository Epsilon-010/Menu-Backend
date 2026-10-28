import secrets
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tables.domain.errors import TableCodeTaken, TableIdTaken, TableNameNotAvailable, TableNotFound
from app.modules.tables.domain.table import PIN_LENGTH, TABLE_CODE_ALPHABET, TABLE_CODE_LENGTH, Table
from app.modules.tables.infrastructure.models import TableModel
from app.shared.infrastructure.database import affected_rows, advisory_xact_lock, violated_unique_constraint

_NAME_INDEX = "uq_tables_tenant_id_lower_name"
_CODE_INDEX = "uq_tables_code"


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
        session_version=model.session_version,
    )


def _raise_name_taken(error: IntegrityError, table: Table) -> None:
    """Another request took the name after the use case checked it."""
    if violated_unique_constraint(error) == _NAME_INDEX:
        raise TableNameNotAvailable(table.name) from error


class SqlAlchemyTableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, table: Table) -> None:
        model = TableModel(
            id=table.id,
            tenant_id=table.tenant_id,
            name=table.name,
            code=table.code,
            pin_hash=table.pin_hash,
            is_active=table.is_active,
            session_version=table.session_version,
        )
        try:
            # A savepoint: when the random code collides, only this insert rolls back and the use
            # case can retry with a new code in the same transaction.
            async with self._session.begin_nested():
                self._session.add(model)
        except IntegrityError as error:
            constraint = violated_unique_constraint(error)
            if constraint == _CODE_INDEX:
                raise TableCodeTaken(table.code) from error
            if constraint == "pk_tables":
                # A concurrent replay of the same create, or a clash with another tenant's id.
                raise TableIdTaken(table.id) from error
            _raise_name_taken(error, table)
            raise

    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None:
        model = await self._session.scalar(
            select(TableModel).where(TableModel.tenant_id == tenant_id, TableModel.id == table_id)
        )
        return _to_entity(model) if model is not None else None

    async def get_for_update(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None:
        model = await self._session.scalar(
            select(TableModel).where(TableModel.tenant_id == tenant_id, TableModel.id == table_id).with_for_update()
        )
        return _to_entity(model) if model is not None else None

    async def exists_anywhere(self, table_id: uuid.UUID) -> bool:
        return await self._session.scalar(select(TableModel.id).where(TableModel.id == table_id)) is not None

    async def lock_creates(self, tenant_id: uuid.UUID) -> None:
        await advisory_xact_lock(self._session, f"tables-create:{tenant_id}")

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
        try:
            result = await self._session.execute(
                update(TableModel)
                .where(TableModel.tenant_id == table.tenant_id, TableModel.id == table.id)
                .values(
                    name=table.name,
                    pin_hash=table.pin_hash,
                    is_active=table.is_active,
                    session_version=table.session_version,
                )
            )
        except IntegrityError as error:
            _raise_name_taken(error, table)
            raise
        if not affected_rows(result):
            raise TableNotFound(table.id)
