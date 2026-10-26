import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.domain.tenant import Tenant
from app.modules.tenants.infrastructure.models import TenantModel


class SqlAlchemyTenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant: Tenant) -> None:
        self._session.add(TenantModel(id=tenant.id, name=tenant.name))
        await self._session.flush()

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        model = await self._session.get(TenantModel, tenant_id)
        return Tenant(id=model.id, name=model.name) if model is not None else None
