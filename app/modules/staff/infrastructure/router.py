import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.revoke_user_sessions import RevokeUserSessions
from app.modules.auth.infrastructure.session_revocation import revoke_user_sessions
from app.modules.staff.application.manage_staff import (
    CreateStaffMember,
    ListStaff,
    ResetStaffPassword,
    UpdateStaffMember,
)
from app.modules.staff.domain.errors import InvalidUserData, StaffMemberNotFound, UsernameNotAvailable
from app.modules.staff.domain.user import User
from app.modules.staff.infrastructure.repository import SqlAlchemyUserRepository
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


class StaffMemberIn(BaseModel):
    username: str = Field(max_length=100)
    full_name: str = Field(max_length=200)
    role: StaffRole
    password: str = Field(max_length=200)


class StaffMemberUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    role: StaffRole | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(max_length=200)


class StaffMemberOut(BaseModel):
    id: uuid.UUID
    username: str | None
    full_name: str
    role: Role
    is_active: bool


def _out(member: User) -> StaffMemberOut:
    return StaffMemberOut(
        id=member.id,
        username=member.username,
        full_name=member.full_name,
        role=member.role,
        is_active=member.is_active,
    )


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


def _session_revoker(request: Request, session: AsyncSession) -> AuthSessionRevoker:
    return AuthSessionRevoker(revoke_user_sessions(request, session))


def get_create_staff_member(session: SessionDep) -> CreateStaffMember:
    return CreateStaffMember(SqlAlchemyUserRepository(session), Argon2PasswordHasher(), SqlAlchemyUnitOfWork(session))


def get_list_staff(session: SessionDep) -> ListStaff:
    return ListStaff(SqlAlchemyUserRepository(session))


def get_update_staff_member(request: Request, session: SessionDep) -> UpdateStaffMember:
    return UpdateStaffMember(
        SqlAlchemyUserRepository(session), _session_revoker(request, session), SqlAlchemyUnitOfWork(session)
    )


def get_reset_staff_password(request: Request, session: SessionDep) -> ResetStaffPassword:
    return ResetStaffPassword(
        SqlAlchemyUserRepository(session),
        Argon2PasswordHasher(),
        _session_revoker(request, session),
        SqlAlchemyUnitOfWork(session),
    )


# --- Routes (admin only; the tenant always comes from the token) -------------------------------


@router.get("", response_model=list[StaffMemberOut])
async def list_staff(admin: Admin, use_case: Annotated[ListStaff, Depends(get_list_staff)]) -> list[StaffMemberOut]:
    return [_out(member) for member in await use_case.execute(admin.tenant_id)]


@router.post("", response_model=StaffMemberOut, status_code=status.HTTP_201_CREATED)
async def create_staff_member(
    body: StaffMemberIn, admin: Admin, use_case: Annotated[CreateStaffMember, Depends(get_create_staff_member)]
) -> StaffMemberOut | JSONResponse:
    try:
        member = await use_case.execute(admin.tenant_id, body.username, body.full_name, Role(body.role), body.password)
    except InvalidUserData as error:
        return _invalid(error)
    except UsernameNotAvailable:
        return problem(status.HTTP_409_CONFLICT, "Username not available")
    return _out(member)


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


@router.put("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_staff_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    admin: Admin,
    use_case: Annotated[ResetStaffPassword, Depends(get_reset_staff_password)],
) -> Response:
    try:
        await use_case.execute(admin.tenant_id, user_id, body.password)
    except InvalidUserData as error:
        return _invalid(error)
    except StaffMemberNotFound:
        return _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
