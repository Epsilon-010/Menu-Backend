import functools
import uuid
import zoneinfo
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.modules.tenants.domain.errors import InvalidTenantData

MAX_NAME_LENGTH = 120
# Days in the statistics are cut in the business's own time zone (IANA name).
DEFAULT_TIMEZONE = "America/Mexico_City"
MAX_TIMEZONE_LENGTH = 64


def validate_timezone(name: str) -> str:
    """Only names of the IANA database are accepted, exactly as spelled there."""
    if name not in _known_timezones():
        raise InvalidTenantData("Unknown time zone")
    return name


@functools.cache
def _known_timezones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


@dataclass(frozen=True)
class Tenant:
    name: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    timezone: str = DEFAULT_TIMEZONE

    @classmethod
    def create(
        cls, name: str, tenant_id: uuid.UUID | None = None, timezone: str | None = None
    ) -> "Tenant":
        """`tenant_id` comes from the client (sign-up) to make the create idempotent; None generates one."""
        name = name.strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise InvalidTenantData(f"Tenant name must have 1 to {MAX_NAME_LENGTH} characters")
        zone = validate_timezone(timezone) if timezone is not None else DEFAULT_TIMEZONE
        return cls(name=name, id=tenant_id or uuid.uuid4(), timezone=zone)

    def with_timezone(self, timezone: str) -> "Tenant":
        return replace(self, timezone=validate_timezone(timezone))


class TenantRepository(Protocol):
    async def add(self, tenant: Tenant) -> None: ...

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None: ...

    async def set_timezone(self, tenant_id: uuid.UUID, timezone: str) -> None: ...
