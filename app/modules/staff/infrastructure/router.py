import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.revoke_user_sessions import RevokeUserSessions
from app.modules.auth.infrastructure.session_revocation import revoke_user_sessions
from app.modules.staff.application.manage_staff import (
    CreateStaffMember,
    ListStaff,
    RegenerateStaffPin,
    StaffMemberWithPin,
    UpdateStaffMember,
)
from app.modules.staff.domain.errors import InvalidUserData, StaffAlreadyCreated, StaffIdTaken, StaffMemberNotFound
from app.modules.staff.domain.user import User
from app.modules.staff.infrastructure.repository import RandomStaffCredentials, SqlAlchemyUserRepository
from app.shared.domain.principal import Principal, Role
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import require_role
from app.shared.infrastructure.http.problems import problem
from app.shared.infrastructure.security import Argon2PasswordHasher

router = APIRouter(prefix="/staff", tags=["staff"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_role("admin"))]
StaffRole = Literal["waiter", "kitchen"]


# --- Schemas -----------------------------------------------------------------------------------


class _In(BaseModel):
    # Unknown fields are rejected instead of silently ignored.
    model_config = ConfigDict(extra="forbid")


class StaffMemberIn(_In):
    # Optional client-chosen id: repeating the create never makes a second member.
    id: uuid.UUID | None = None
    # Only a name: the code and the PIN are generated.
    full_name: str = Field(max_length=200)
    role: StaffRole


class StaffMemberUpdate(_In):
    full_name: str | None = Field(default=None, max_length=200)
    role: StaffRole | None = None
    is_active: bool | None = None


class StaffMemberOut(BaseModel):
    id: uuid.UUID
    # The login of the member (with the PIN), unique across the platform; typed in any case.
    code: str
    full_name: str
    role: Role
    is_active: bool


class StaffMemberWithPinOut(StaffMemberOut):
    # Shown only in this response: the backend keeps just its hash.
    pin: str


def _out(member: User) -> StaffMemberOut:
    return StaffMemberOut(
        id=member.id,
        code=member.code,
        full_name=member.full_name,
        role=member.role,
        is_active=member.is_active,
    )


def _with_pin(result: StaffMemberWithPin) -> StaffMemberWithPinOut:
    return StaffMemberWithPinOut(**_out(result.member).model_dump(), pin=result.pin)


def _invalid(error: InvalidUserData) -> JSONResponse:
    return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


def _not_found() -> JSONResponse:
    return problem(status.HTTP_404_NOT_FOUND, "Staff member not found")


# --- Wiring ------------------------------------------------------------------------------------


class AuthSessionRevoker:
    """Adapter of the staff `SessionRevoker` port onto the auth module's use case."""

    def __init__(self, revoke: RevokeUserSessions) -> None:
        self._revoke = revoke

    async def revoke_all(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._revoke.execute(tenant_id, user_id)

    async def end_access(self, user_id: uuid.UUID, session_version: int) -> None:
        await self._revoke.end_access(user_id, session_version)


def _session_revoker(request: Request, session: AsyncSession) -> AuthSessionRevoker:
    return AuthSessionRevoker(revoke_user_sessions(request, session))


def get_create_staff_member(session: SessionDep) -> CreateStaffMember:
    return CreateStaffMember(
        SqlAlchemyUserRepository(session), RandomStaffCredentials(), Argon2PasswordHasher(), SqlAlchemyUnitOfWork(session)
    )


def get_list_staff(session: SessionDep) -> ListStaff:
    return ListStaff(SqlAlchemyUserRepository(session))


def get_update_staff_member(request: Request, session: SessionDep) -> UpdateStaffMember:
    return UpdateStaffMember(
        SqlAlchemyUserRepository(session), _session_revoker(request, session), SqlAlchemyUnitOfWork(session)
    )


def get_regenerate_staff_pin(request: Request, session: SessionDep) -> RegenerateStaffPin:
    return RegenerateStaffPin(
        SqlAlchemyUserRepository(session),
        RandomStaffCredentials(),
        Argon2PasswordHasher(),
        _session_revoker(request, session),
        SqlAlchemyUnitOfWork(session),
    )


# --- Routes (admin only; the tenant always comes from the token) -------------------------------


@router.get("", response_model=list[StaffMemberOut])
async def list_staff(admin: Admin, use_case: Annotated[ListStaff, Depends(get_list_staff)]) -> list[StaffMemberOut]:
    return [_out(member) for member in await use_case.execute(admin.tenant_id)]


@router.post("", response_model=StaffMemberWithPinOut, status_code=status.HTTP_201_CREATED)
async def create_staff_member(
    body: StaffMemberIn, admin: Admin, use_case: Annotated[CreateStaffMember, Depends(get_create_staff_member)]
) -> StaffMemberWithPinOut | JSONResponse:
    try:
        result = await use_case.execute(admin.tenant_id, body.full_name, Role(body.role), body.id)
    except InvalidUserData as error:
        return _invalid(error)
    except StaffAlreadyCreated:
        return problem(
            status.HTTP_409_CONFLICT,
            "This staff member was already created; generate a new PIN to see the credentials",
        )
    except StaffIdTaken:
        return problem(status.HTTP_409_CONFLICT, "That id is already used by something else")
    return _with_pin(result)


@router.patch("/{user_id}", response_model=StaffMemberOut)
async def update_staff_member(
    user_id: uuid.UUID,
    body: StaffMemberUpdate,
    admin: Admin,
    use_case: Annotated[UpdateStaffMember, Depends(get_update_staff_member)],
) -> StaffMemberOut | JSONResponse:
    try:
        member = await use_case.execute(
            admin.tenant_id,
            user_id,
            full_name=body.full_name,
            role=Role(body.role) if body.role is not None else None,
            is_active=body.is_active,
        )
    except InvalidUserData as error:
        return _invalid(error)
    except StaffMemberNotFound:
        return _not_found()
    return _out(member)


@router.post("/{user_id}/pin", response_model=StaffMemberWithPinOut)
async def regenerate_staff_pin(
    user_id: uuid.UUID, admin: Admin, use_case: Annotated[RegenerateStaffPin, Depends(get_regenerate_staff_pin)]
) -> StaffMemberWithPinOut | JSONResponse:
    """New PIN (the code stays); every session of the member ends."""
    try:
        result = await use_case.execute(admin.tenant_id, user_id)
    except StaffMemberNotFound:
        return _not_found()
    return _with_pin(result)
