from dataclasses import dataclass

from app.modules.auth.domain.errors import AccountNotFound
from app.modules.orders.application.guests import GetActiveGuest
from app.modules.orders.domain.model import Guest
from app.modules.staff.application.find_user import GetUser
from app.modules.staff.domain.user import User
from app.modules.tables.application.find_table import GetTable
from app.modules.tables.domain.table import Table
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.tenant import Tenant
from app.shared.domain.principal import Principal, Role


@dataclass(frozen=True)
class Account:
    """Who is signed in: a staff `user`, a `table` device, or a QR `guest` (with the `table` they joined)."""

    tenant: Tenant
    user: User | None = None
    table: Table | None = None
    guest: Guest | None = None


class GetCurrentAccount:
    def __init__(
        self, get_user: GetUser, get_table: GetTable, get_tenant: GetTenant, get_guest: GetActiveGuest
    ) -> None:
        self._get_user = get_user
        self._get_table = get_table
        self._get_tenant = get_tenant
        self._get_guest = get_guest

    async def execute(self, principal: Principal) -> Account:
        # Every lookup is scoped to the tenant carried by the token.
        tenant = await self._get_tenant.execute(principal.tenant_id)
        if tenant is None:
            raise AccountNotFound()
        if principal.role is Role.GUEST:
            guest = await self._get_guest.execute(principal.tenant_id, principal.subject_id)
            if guest is None or guest.bill_id != principal.bill_id:
                raise AccountNotFound()
            guest_table = await self._get_table.execute(principal.tenant_id, guest.table_id)
            if guest_table is None or not guest_table.is_active:
                raise AccountNotFound()
            return Account(tenant=tenant, table=guest_table, guest=guest)
        if principal.role is Role.TABLE:
            table = (
                await self._get_table.execute(principal.tenant_id, principal.table_id)
                if principal.table_id is not None
                else None
            )
            if table is None or not table.is_active or table.session_version != principal.session_version:
                raise AccountNotFound()
            return Account(tenant=tenant, table=table)

        user = await self._get_user.execute(principal.tenant_id, principal.subject_id)
        if user is None or not user.is_active or user.session_version != principal.session_version:
            raise AccountNotFound()
        return Account(tenant=tenant, user=user)
