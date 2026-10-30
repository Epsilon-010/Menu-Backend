import uuid

import pytest

from app.modules.tenants.application.create_tenant import CreateTenant
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.application.set_timezone import SetTenantTimezone
from app.modules.tenants.domain.errors import InvalidTenantData
from app.modules.tenants.domain.tenant import DEFAULT_TIMEZONE
from tests.unit.fakes import FakeUnitOfWork, InMemoryTenantRepository

pytestmark = pytest.mark.anyio


async def test_creates_a_tenant_with_a_trimmed_name() -> None:
    tenants, uow = InMemoryTenantRepository(), FakeUnitOfWork()

    tenant = await CreateTenant(tenants, uow).execute("  La Taquería  ")

    assert tenant.name == "La Taquería"
    assert isinstance(tenant.id, uuid.UUID)
    assert await GetTenant(tenants).execute(tenant.id) == tenant
    assert uow.commits == 1


async def test_rejects_a_blank_tenant_name() -> None:
    tenants, uow = InMemoryTenantRepository(), FakeUnitOfWork()

    with pytest.raises(InvalidTenantData):
        await CreateTenant(tenants, uow).execute("   ")

    assert tenants.tenants == {}
    assert uow.commits == 0


async def test_get_tenant_returns_none_for_an_unknown_id() -> None:
    assert await GetTenant(InMemoryTenantRepository()).execute(uuid.uuid4()) is None


# --- Time zone (Slice 16, S1) ----------------------------------------------------------------------


async def test_a_new_tenant_uses_the_default_time_zone_unless_given_one() -> None:
    tenants, uow = InMemoryTenantRepository(), FakeUnitOfWork()

    default = await CreateTenant(tenants, uow).execute("Tacos")
    chosen = await CreateTenant(tenants, uow).execute("Burgers", timezone="Europe/Madrid")

    assert default.timezone == DEFAULT_TIMEZONE == "America/Mexico_City"
    assert chosen.timezone == "Europe/Madrid"


@pytest.mark.parametrize("zone", ["Mars/Olympus", "", "america/mexico_city", "../etc/passwd", "UTC\u0000"])
async def test_an_unknown_time_zone_is_rejected(zone: str) -> None:
    tenants, uow = InMemoryTenantRepository(), FakeUnitOfWork()

    with pytest.raises(InvalidTenantData, match="Unknown time zone"):
        await CreateTenant(tenants, uow).execute("Tacos", timezone=zone)

    assert tenants.tenants == {}


async def test_the_admin_changes_the_time_zone_of_their_tenant_only() -> None:
    tenants, uow = InMemoryTenantRepository(), FakeUnitOfWork()
    mine = await CreateTenant(tenants, uow).execute("Tacos")
    other = await CreateTenant(tenants, uow).execute("Burgers")

    updated = await SetTenantTimezone(tenants, uow).execute(mine.id, "America/Bogota")

    assert updated.timezone == "America/Bogota"
    assert (await GetTenant(tenants).execute(mine.id)).timezone == "America/Bogota"  # type: ignore[union-attr]
    assert (await GetTenant(tenants).execute(other.id)).timezone == DEFAULT_TIMEZONE  # type: ignore[union-attr]
    assert uow.commits == 3


async def test_changing_to_an_unknown_time_zone_changes_nothing() -> None:
    tenants, uow = InMemoryTenantRepository(), FakeUnitOfWork()
    tenant = await CreateTenant(tenants, uow).execute("Tacos")

    with pytest.raises(InvalidTenantData, match="Unknown time zone"):
        await SetTenantTimezone(tenants, uow).execute(tenant.id, "Nowhere/City")

    assert (await GetTenant(tenants).execute(tenant.id)).timezone == DEFAULT_TIMEZONE  # type: ignore[union-attr]
    assert uow.commits == 1
