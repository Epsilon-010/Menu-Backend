import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.modules.staff.application.manage_admins import (
    AdminWithTemporaryPassword,
    CreateAdmin,
    ListAdmins,
    UpdateAdmin,
)
from app.modules.staff.domain.errors import (
    AdminAlreadyCreated,
    AdminNotFound,
    CannotDeactivateSelf,
    EmailAlreadyInUse,
    InvalidUserData,
    NotAnActiveAdmin,
    StaffIdTaken,
)
from app.modules.staff.domain.user import User
from app.modules.staff.infrastructure.repository import RandomStaffCredentials, SqlAlchemyUserRepository
from app.modules.staff.infrastructure.router import SessionDep, _session_revoker
from app.shared.domain.principal import Principal
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork
from app.shared.infrastructure.http.auth import require_role
from app.shared.infrastructure.http.problems import problem
from app.shared.infrastructure.security import Argon2PasswordHasher

router = APIRouter(prefix="/admins", tags=["admins"])

Admin = Annotated[Principal, Depends(require_role("admin"))]


# --- Schemas -----------------------------------------------------------------------------------


class _In(BaseModel):
    # Unknown fields are rejected instead of silently ignored.
    model_config = ConfigDict(extra="forbid")


class AdminIn(_In):
    # Optional client-chosen id: repeating the create never makes a second admin.
    id: uuid.UUID | None = None
    full_name: str = Field(max_length=200)
    email: str = Field(max_length=254)


class AdminUpdate(_In):
    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class AdminOut(BaseModel):
    id: uuid.UUID
    email: str | None
    full_name: str
    is_active: bool
    # Still on the temporary password the creating admin handed over.
    must_change_password: bool


class AdminWithTemporaryPasswordOut(AdminOut):
    # Shown only in this response: the backend keeps just its hash.
    temporary_password: str


def _out(admin: User) -> AdminOut:
    return AdminOut(
        id=admin.id,
        email=admin.email,
        full_name=admin.full_name,
        is_active=admin.is_active,
        must_change_password=admin.must_change_password,
    )


def _with_password(result: AdminWithTemporaryPassword) -> AdminWithTemporaryPasswordOut:
    return AdminWithTemporaryPasswordOut(
        **_out(result.admin).model_dump(), temporary_password=result.temporary_password
    )


# --- Wiring ------------------------------------------------------------------------------------


def get_create_admin(session: SessionDep) -> CreateAdmin:
    return CreateAdmin(
        SqlAlchemyUserRepository(session), RandomStaffCredentials(), Argon2PasswordHasher(), SqlAlchemyUnitOfWork(session)
    )


def get_list_admins(session: SessionDep) -> ListAdmins:
    return ListAdmins(SqlAlchemyUserRepository(session))


def get_update_admin(request: Request, session: SessionDep) -> UpdateAdmin:
    return UpdateAdmin(
        SqlAlchemyUserRepository(session), _session_revoker(request, session), SqlAlchemyUnitOfWork(session)
    )


# --- Routes (admin only; the tenant always comes from the token) -------------------------------


@router.get("", response_model=list[AdminOut])
async def list_admins(admin: Admin, use_case: Annotated[ListAdmins, Depends(get_list_admins)]) -> list[AdminOut]:
    return [_out(item) for item in await use_case.execute(admin.tenant_id)]


@router.post("", response_model=AdminWithTemporaryPasswordOut, status_code=status.HTTP_201_CREATED)
async def create_admin(
    body: AdminIn, admin: Admin, use_case: Annotated[CreateAdmin, Depends(get_create_admin)]
) -> AdminWithTemporaryPasswordOut | JSONResponse:
    try:
        result = await use_case.execute(admin.tenant_id, body.full_name, body.email, body.id)
    except InvalidUserData as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except EmailAlreadyInUse:
        return problem(status.HTTP_409_CONFLICT, "Email already in use")
    except AdminAlreadyCreated:
        return problem(status.HTTP_409_CONFLICT, "This admin was already created")
    except StaffIdTaken:
        return problem(status.HTTP_409_CONFLICT, "That id is already used by something else")
    return _with_password(result)


@router.patch("/{user_id}", response_model=AdminOut)
async def update_admin(
    user_id: uuid.UUID, body: AdminUpdate, admin: Admin, use_case: Annotated[UpdateAdmin, Depends(get_update_admin)]
) -> AdminOut | JSONResponse:
    """Renames or (de)activates another admin; deactivating ends their sessions right away."""
    try:
        updated = await use_case.execute(
            admin.tenant_id, admin.subject_id, user_id, full_name=body.full_name, is_active=body.is_active
        )
    except InvalidUserData as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except NotAnActiveAdmin:
        return problem(status.HTTP_403_FORBIDDEN, "Not allowed")
    except AdminNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Admin not found")
    except CannotDeactivateSelf:
        return problem(status.HTTP_409_CONFLICT, "You cannot deactivate your own account")
    return _out(updated)
