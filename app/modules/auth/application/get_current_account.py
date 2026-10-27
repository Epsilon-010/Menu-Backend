from dataclasses import dataclass

from app.modules.auth.domain.errors import AccountNotFound
from app.modules.staff.application.find_user import GetUser
from app.modules.staff.domain.user import User
from app.modules.tables.application.find_table import GetTable
from app.modules.tables.domain.table import Table
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.tenant import Tenant
from app.shared.domain.principal import Principal, Role


@dataclass(frozen=True)
class Account:
    """Who is signed in: a staff `user`, or a `table` device (exactly one of them)."""

    tenant: Tenant
    user: User | None = None
    table: Table | None = None


class GetCurrentAccount:
    def __init__(self, get_user: GetUser, get_table: GetTable, get_tenant: GetTenant) -> None:
        self._get_user = get_user
        self._get_table = get_table
        self._get_tenant = get_tenant

    async def execute(self, principal: Principal) -> Account:
        # Every lookup is scoped to the tenant carried by the token.
        tenant = await self._get_tenant.execute(principal.tenant_id)
        if tenant is None:
            raise AccountNotFound()
        if principal.role is Role.TABLE:
            table = (
                await self._get_table.execute(principal.tenant_id, principal.table_id)
                if principal.table_id is not None
                else None
            )
            if table is None or not table.is_active:
                raise AccountNotFound()
            return Account(tenant=tenant, table=table)

        user = await self._get_user.execute(principal.tenant_id, principal.subject_id)
        if user is None or not user.is_active:
            raise AccountNotFound()
        return Account(tenant=tenant, user=user)
