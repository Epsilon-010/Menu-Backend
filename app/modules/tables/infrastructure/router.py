import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.revoke_user_sessions import RevokeTableSessions
from app.modules.auth.infrastructure.session_revocation import revoke_table_sessions
from app.modules.orders.infrastructure.guest_sessions import table_guest_sessions
from app.modules.tables.application.manage_tables import (
    CreateTable,
    ListTables,
    RegenerateTablePin,
    RegenerateTableQr,
    TableWithPin,
    UpdateTable,
)
from app.modules.tables.domain.errors import (
    InvalidTableData,
    TableAlreadyCreated,
    TableIdTaken,
    TableNameNotAvailable,
    TableNotFound,
)
from app.modules.tables.domain.table import Table
from app.modules.tables.infrastructure.repository import RandomTableCredentials, SqlAlchemyTableRepository
from app.shared.domain.principal import Principal
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import require_role
from app.shared.infrastructure.http.problems import problem
from app.shared.infrastructure.security import Argon2PasswordHasher

router = APIRouter(prefix="/tables", tags=["tables"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_role("admin"))]


# --- Schemas -----------------------------------------------------------------------------------


class _In(BaseModel):
    # Unknown fields are rejected instead of silently ignored.
    model_config = ConfigDict(extra="forbid")


class TableIn(_In):
    # Optional client-chosen id: repeating the create never makes a second table.
    id: uuid.UUID | None = None
    name: str = Field(max_length=200)


class TableUpdate(_In):
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class TableOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    is_active: bool
    # The random part of the table's QR link (`/q/<qr_token>`); printing it again needs no new QR.
    qr_token: str | None


class TableWithPinOut(TableOut):
    """Only returned when the PIN is created or regenerated: it is never shown again."""

    pin: str


def _out(table: Table) -> TableOut:
    return TableOut(id=table.id, name=table.name, code=table.code, is_active=table.is_active, qr_token=table.qr_token)


def _with_pin(result: TableWithPin) -> TableWithPinOut:
    return TableWithPinOut(**_out(result.table).model_dump(), pin=result.pin)


def _invalid(error: InvalidTableData) -> JSONResponse:
    return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


def _name_taken() -> JSONResponse:
    return problem(status.HTTP_409_CONFLICT, "Table name already in use")


def _not_found() -> JSONResponse:
    return problem(status.HTTP_404_NOT_FOUND, "Table not found")


# --- Wiring ------------------------------------------------------------------------------------


class AuthTableSessionRevoker:
    """Adapter of the tables `SessionRevoker` port onto the auth module's use case."""

    def __init__(self, revoke: RevokeTableSessions) -> None:
        self._revoke = revoke

    async def revoke_all(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        await self._revoke.execute(tenant_id, table_id)

    async def end_access(self, table_id: uuid.UUID, session_version: int) -> None:
        await self._revoke.end_access(table_id, session_version)


def _session_revoker(request: Request, session: AsyncSession) -> AuthTableSessionRevoker:
    return AuthTableSessionRevoker(revoke_table_sessions(request, session))


def get_create_table(session: SessionDep) -> CreateTable:
    return CreateTable(
        SqlAlchemyTableRepository(session), RandomTableCredentials(), Argon2PasswordHasher(), SqlAlchemyUnitOfWork(session)
    )


def get_list_tables(session: SessionDep) -> ListTables:
    return ListTables(SqlAlchemyTableRepository(session))


def get_update_table(request: Request, session: SessionDep) -> UpdateTable:
    return UpdateTable(
        SqlAlchemyTableRepository(session),
        _session_revoker(request, session),
        table_guest_sessions(request, session),
        SqlAlchemyUnitOfWork(session),
    )


def get_regenerate_table_qr(request: Request, session: SessionDep) -> RegenerateTableQr:
    return RegenerateTableQr(
        SqlAlchemyTableRepository(session),
        RandomTableCredentials(),
        table_guest_sessions(request, session),
        SqlAlchemyUnitOfWork(session),
    )


def get_regenerate_table_pin(request: Request, session: SessionDep) -> RegenerateTablePin:
    return RegenerateTablePin(
        SqlAlchemyTableRepository(session),
        RandomTableCredentials(),
        Argon2PasswordHasher(),
        _session_revoker(request, session),
        SqlAlchemyUnitOfWork(session),
    )


# --- Routes (admin only; the tenant always comes from the token) -------------------------------


@router.get("", response_model=list[TableOut])
async def list_tables(admin: Admin, use_case: Annotated[ListTables, Depends(get_list_tables)]) -> list[TableOut]:
    return [_out(table) for table in await use_case.execute(admin.tenant_id)]


@router.post("", response_model=TableWithPinOut, status_code=status.HTTP_201_CREATED)
async def create_table(
    body: TableIn, admin: Admin, use_case: Annotated[CreateTable, Depends(get_create_table)]
) -> TableWithPinOut | JSONResponse:
    try:
        result = await use_case.execute(admin.tenant_id, body.name, body.id)
    except InvalidTableData as error:
        return _invalid(error)
    except TableNameNotAvailable:
        return _name_taken()
    except TableAlreadyCreated:
        return problem(status.HTTP_409_CONFLICT, "This table was already created; generate a new PIN to see its credentials")
    except TableIdTaken:
        return problem(status.HTTP_409_CONFLICT, "That id is already used by something else")
    return _with_pin(result)


@router.patch("/{table_id}", response_model=TableOut)
async def update_table(
    table_id: uuid.UUID, body: TableUpdate, admin: Admin, use_case: Annotated[UpdateTable, Depends(get_update_table)]
) -> TableOut | JSONResponse:
    try:
        table = await use_case.execute(admin.tenant_id, table_id, name=body.name, is_active=body.is_active)
    except InvalidTableData as error:
        return _invalid(error)
    except TableNameNotAvailable:
        return _name_taken()
    except TableNotFound:
        return _not_found()
    return _out(table)


@router.post("/{table_id}/pin", response_model=TableWithPinOut)
async def regenerate_table_pin(
    table_id: uuid.UUID, admin: Admin, use_case: Annotated[RegenerateTablePin, Depends(get_regenerate_table_pin)]
) -> TableWithPinOut | JSONResponse:
    try:
        result = await use_case.execute(admin.tenant_id, table_id)
    except TableNotFound:
        return _not_found()
    return _with_pin(result)


@router.post("/{table_id}/qr", response_model=TableOut)
async def regenerate_table_qr(
    table_id: uuid.UUID, admin: Admin, use_case: Annotated[RegenerateTableQr, Depends(get_regenerate_table_qr)]
) -> TableOut | JSONResponse:
    try:
        table = await use_case.execute(admin.tenant_id, table_id)
    except TableNotFound:
        return _not_found()
    return _out(table)
