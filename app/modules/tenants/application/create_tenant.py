import uuid

from app.modules.tenants.domain.tenant import Tenant, TenantRepository
from app.shared.domain.ports import UnitOfWork


class CreateTenant:
    def __init__(self, tenants: TenantRepository, uow: UnitOfWork) -> None:
        self._tenants = tenants
        self._uow = uow

    async def execute(self, name: str, tenant_id: uuid.UUID | None = None) -> Tenant:
        tenant = Tenant.create(name, tenant_id)
        await self._tenants.add(tenant)
        await self._uow.commit()
        return tenant
