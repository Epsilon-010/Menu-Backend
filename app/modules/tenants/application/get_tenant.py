import uuid

from app.modules.tenants.domain.tenant import Tenant, TenantRepository


class GetTenant:
    def __init__(self, tenants: TenantRepository) -> None:
        self._tenants = tenants

    async def execute(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self._tenants.get(tenant_id)
