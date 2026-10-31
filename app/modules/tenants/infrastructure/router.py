from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.application.set_timezone import SetTenantTimezone
from app.modules.tenants.domain.errors import InvalidTenantData, TenantNotFound
from app.modules.tenants.domain.tenant import MAX_TIMEZONE_LENGTH
from app.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository
from app.shared.domain.principal import Principal
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import require_role
from app.shared.infrastructure.http.problems import problem

router = APIRouter(prefix="/tenant", tags=["tenant"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_role("admin"))]


class TenantSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(max_length=MAX_TIMEZONE_LENGTH)


class TenantSettingsOut(BaseModel):
    timezone: str


def _not_found() -> JSONResponse:
    return problem(status.HTTP_404_NOT_FOUND, "Business not found")


@router.get("/settings", response_model=TenantSettingsOut)
async def read_settings(admin: Admin, session: SessionDep) -> TenantSettingsOut | JSONResponse:
    tenant = await GetTenant(SqlAlchemyTenantRepository(session)).execute(admin.tenant_id)
    return _not_found() if tenant is None else TenantSettingsOut(timezone=tenant.timezone)


@router.patch("/settings", response_model=TenantSettingsOut)
async def update_settings(
    body: TenantSettingsIn, admin: Admin, session: SessionDep
) -> TenantSettingsOut | JSONResponse:
    use_case = SetTenantTimezone(SqlAlchemyTenantRepository(session), SqlAlchemyUnitOfWork(session))
    try:
        tenant = await use_case.execute(admin.tenant_id, body.timezone)
    except InvalidTenantData as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except TenantNotFound:
        return _not_found()
    return TenantSettingsOut(timezone=tenant.timezone)
