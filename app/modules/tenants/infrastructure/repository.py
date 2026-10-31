import uuid

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.domain.errors import TenantIdTaken
from app.modules.tenants.domain.tenant import Tenant
from app.modules.tenants.infrastructure.models import TenantModel
from app.shared.infrastructure.database import violated_unique_constraint


class SqlAlchemyTenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant: Tenant) -> None:
        self._session.add(TenantModel(id=tenant.id, name=tenant.name, timezone=tenant.timezone))
        try:
            await self._session.flush()
        except IntegrityError as error:
            # A client-chosen id (sign-up) that a concurrent request took first.
            if violated_unique_constraint(error) == "pk_tenants":
                raise TenantIdTaken(tenant.id) from error
            raise

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        model = await self._session.get(TenantModel, tenant_id)
        return Tenant(id=model.id, name=model.name, timezone=model.timezone) if model is not None else None

    async def set_timezone(self, tenant_id: uuid.UUID, timezone: str) -> None:
        await self._session.execute(update(TenantModel).where(TenantModel.id == tenant_id).values(timezone=timezone))
