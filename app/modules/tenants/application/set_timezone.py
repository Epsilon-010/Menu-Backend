import uuid

from app.modules.tenants.domain.errors import TenantNotFound
from app.modules.tenants.domain.tenant import Tenant, TenantRepository
from app.shared.domain.ports import UnitOfWork


class SetTenantTimezone:
    """The admin picks the time zone in which the business's days (statistics) are cut."""

    def __init__(self, tenants: TenantRepository, uow: UnitOfWork) -> None:
        self._tenants = tenants
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, timezone: str) -> Tenant:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFound(tenant_id)
        updated = tenant.with_timezone(timezone)
        await self._tenants.set_timezone(tenant_id, updated.timezone)
        await self._uow.commit()
        return updated
