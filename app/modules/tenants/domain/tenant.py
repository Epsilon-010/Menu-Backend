import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.modules.tenants.domain.errors import InvalidTenantData

MAX_NAME_LENGTH = 120


@dataclass(frozen=True)
class Tenant:
    name: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(cls, name: str, tenant_id: uuid.UUID | None = None) -> "Tenant":
        """`tenant_id` comes from the client (sign-up) to make the create idempotent; None generates one."""
        name = name.strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise InvalidTenantData(f"Tenant name must have 1 to {MAX_NAME_LENGTH} characters")
        return cls(name=name, id=tenant_id or uuid.uuid4())


class TenantRepository(Protocol):
    async def add(self, tenant: Tenant) -> None: ...

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None: ...
