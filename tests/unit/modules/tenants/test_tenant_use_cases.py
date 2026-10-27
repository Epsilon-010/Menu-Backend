import uuid

import pytest

from app.modules.tenants.application.create_tenant import CreateTenant
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.errors import InvalidTenantData
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
