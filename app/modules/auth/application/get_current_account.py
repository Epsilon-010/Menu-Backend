from dataclasses import dataclass

from app.modules.auth.domain.errors import AccountNotFound
from app.modules.staff.application.find_user import GetUser
from app.modules.staff.domain.user import User
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.tenant import Tenant
from app.shared.domain.principal import Principal


@dataclass(frozen=True)
class Account:
    user: User
    tenant: Tenant


class GetCurrentAccount:
    def __init__(self, get_user: GetUser, get_tenant: GetTenant) -> None:
        self._get_user = get_user
        self._get_tenant = get_tenant

    async def execute(self, principal: Principal) -> Account:
        # Both lookups are scoped to the tenant carried by the token.
        user = await self._get_user.execute(principal.tenant_id, principal.subject_id)
        tenant = await self._get_tenant.execute(principal.tenant_id)
        if user is None or not user.is_active or tenant is None:
            raise AccountNotFound()
        return Account(user=user, tenant=tenant)
