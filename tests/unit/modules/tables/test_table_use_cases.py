import uuid

import pytest

from app.modules.tables.application.find_table import FindTableByCode, GetTable
from app.modules.tables.application.manage_tables import CreateTable, ListTables, RegenerateTablePin, UpdateTable
from app.modules.tables.domain.errors import (
    InvalidTableData,
    TableAlreadyCreated,
    TableCodeTaken,
    TableIdTaken,
    TableNameNotAvailable,
    TableNotFound,
)
from app.modules.tables.domain.table import Table
from tests.unit.fakes import FakePasswordHasher, FakeTableCredentials, FakeUnitOfWork, InMemoryTableRepository

pytestmark = pytest.mark.anyio

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


class FakeSessionRevoker:
    def __init__(self) -> None:
        self.revoked: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.access_ended: list[tuple[uuid.UUID, int]] = []

    async def revoke_all(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        self.revoked.append((tenant_id, table_id))

    async def end_access(self, table_id: uuid.UUID, session_version: int) -> None:
        self.access_ended.append((table_id, session_version))


class World:
    def __init__(self, codes: list[str] | None = None) -> None:
        self.tables = InMemoryTableRepository()
        self.credentials = FakeTableCredentials(codes)
        self.hasher = FakePasswordHasher()
        self.sessions = FakeSessionRevoker()
        self.uow = FakeUnitOfWork()

    def create(self) -> CreateTable:
        return CreateTable(self.tables, self.credentials, self.hasher, self.uow)

    def update(self) -> UpdateTable:
        return UpdateTable(self.tables, self.sessions, self.uow)

    def regenerate(self) -> RegenerateTablePin:
        return RegenerateTablePin(self.tables, self.credentials, self.hasher, self.sessions, self.uow)

    async def add(self, name: str = "Mesa 4", tenant_id: uuid.UUID = TENANT_A) -> Table:
        return (await self.create().execute(tenant_id, name)).table


@pytest.fixture
def world() -> World:
    return World()


# --- Create ------------------------------------------------------------------------------------


async def test_creating_a_table_generates_a_code_and_a_pin_shown_once_and_stored_hashed(world: World) -> None:
    created = await world.create().execute(TENANT_A, "  Mesa 4 ")

    table = created.table
    assert table.name == "Mesa 4"
    assert table.tenant_id == TENANT_A
    assert table.code == "CODE01"
    assert table.is_active is True
    assert created.pin == "000001"
    assert table.pin_hash == "hashed:000001"
    assert world.tables.tables[table.id] == table
    assert world.uow.commits == 1


async def test_table_codes_are_unique_across_tenants(world: World) -> None:
    world.credentials.codes = ["TAKEN1", "TAKEN1", "FREE22"]
    first = await world.add("Mesa 1", TENANT_B)

    second = await world.add("Mesa 1", TENANT_A)

    assert first.code == "TAKEN1"
    assert second.code == "FREE22"


async def test_table_names_are_unique_per_tenant_ignoring_case(world: World) -> None:
    await world.add("Mesa 4")

    with pytest.raises(TableNameNotAvailable):
        await world.create().execute(TENANT_A, " mesa 4")
    # Another tenant can use the same name.
    other = await world.add("Mesa 4", TENANT_B)

    assert other.tenant_id == TENANT_B
    assert len(world.tables.tables) == 2


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
async def test_rejects_invalid_names(world: World, name: str) -> None:
    with pytest.raises(InvalidTableData):
        await world.create().execute(TENANT_A, name)

    assert world.tables.tables == {}
    assert world.uow.commits == 0


# --- List --------------------------------------------------------------------------------------


async def test_lists_only_the_tenant_tables_ordered_by_name(world: World) -> None:
    await world.add("Mesa 2")
    await world.add("mesa 1")
    await world.add("Mesa 9", TENANT_B)

    tables = await ListTables(world.tables).execute(TENANT_A)

    assert [table.name for table in tables] == ["mesa 1", "Mesa 2"]


# --- Update ------------------------------------------------------------------------------------


async def test_deactivating_a_table_ends_its_sessions(world: World) -> None:
    table = await world.add()

    updated = await world.update().execute(TENANT_A, table.id, is_active=False)

    assert updated.is_active is False
    assert world.tables.tables[table.id].is_active is False
    assert world.sessions.revoked == [(TENANT_A, table.id)]


async def test_renaming_keeps_the_sessions_and_the_credentials(world: World) -> None:
    table = await world.add()

    updated = await world.update().execute(TENANT_A, table.id, name="Terraza 1")

    assert updated.name == "Terraza 1"
    assert updated.code == table.code
    assert updated.pin_hash == table.pin_hash
    assert world.sessions.revoked == []


async def test_renaming_to_another_table_name_is_rejected_but_changing_its_case_is_not(world: World) -> None:
    await world.add("Mesa 1")
    table = await world.add("Mesa 2")

    with pytest.raises(TableNameNotAvailable):
        await world.update().execute(TENANT_A, table.id, name="MESA 1")
    renamed = await world.update().execute(TENANT_A, table.id, name="MESA 2")

    assert renamed.name == "MESA 2"


async def test_another_tenant_table_is_not_found(world: World) -> None:
    table = await world.add(tenant_id=TENANT_B)

    with pytest.raises(TableNotFound):
        await world.update().execute(TENANT_A, table.id, is_active=False)
    with pytest.raises(TableNotFound):
        await world.regenerate().execute(TENANT_A, table.id)

    assert world.tables.tables[table.id] == table
    assert world.sessions.revoked == []


# --- Regenerate PIN ----------------------------------------------------------------------------


async def test_regenerating_the_pin_keeps_the_code_and_ends_the_sessions(world: World) -> None:
    table = await world.add()

    regenerated = await world.regenerate().execute(TENANT_A, table.id)

    assert regenerated.pin == "000002"
    assert regenerated.table.code == table.code
    assert world.tables.tables[table.id].pin_hash == "hashed:000002"
    assert world.sessions.revoked == [(TENANT_A, table.id)]
    assert world.uow.commits == 2


# --- Lookups -----------------------------------------------------------------------------------


async def test_finds_a_table_by_code_ignoring_case_and_spaces(world: World) -> None:
    table = await world.add()

    assert await FindTableByCode(world.tables).execute("  code01 ") == table
    assert await FindTableByCode(world.tables).execute("NOPE00") is None


async def test_gets_a_table_only_inside_its_tenant(world: World) -> None:
    table = await world.add()

    assert await GetTable(world.tables).execute(TENANT_A, table.id) == table
    assert await GetTable(world.tables).execute(TENANT_B, table.id) is None


async def test_every_write_locks_the_table_it_rewrites(world: World) -> None:
    table = await world.add()

    await world.update().execute(TENANT_A, table.id, name="Terraza 1")
    await world.regenerate().execute(TENANT_A, table.id)

    assert world.tables.locked == [table.id, table.id]


async def test_repeating_a_table_create_never_makes_a_second_table(world: World) -> None:
    table_id = uuid.uuid4()
    created = await world.create().execute(TENANT_A, "Mesa 4", table_id)

    # The PIN exists only in the first response (it is stored hashed), so a replay cannot show it.
    with pytest.raises(TableAlreadyCreated):
        await world.create().execute(TENANT_A, "Mesa 4", table_id)
    with pytest.raises(TableIdTaken):
        await world.create().execute(TENANT_B, "Mesa 4", table_id)

    assert created.table.id == table_id
    assert list(world.tables.tables) == [table_id]


class RacyTables(InMemoryTableRepository):
    """Another request inserts the same code between our check and our insert."""

    async def get_by_code(self, code: str) -> Table | None:
        return None

    async def add(self, table: Table) -> None:
        if any(existing.code == table.code for existing in self.tables.values()):
            raise TableCodeTaken(table.code)
        await super().add(table)


async def test_a_code_taken_by_a_concurrent_create_is_redrawn_not_a_500(world: World) -> None:
    racy = RacyTables()
    world.tables = racy
    world.credentials.codes = ["SAME22", "SAME22", "OTHER3"]
    first = (await world.create().execute(TENANT_A, "Mesa 1")).table

    second = (await world.create().execute(TENANT_B, "Mesa 1")).table

    assert (first.code, second.code) == ("SAME22", "OTHER3")


async def test_table_creates_of_a_tenant_are_serialized(world: World) -> None:
    await world.create().execute(TENANT_A, "Mesa 4", uuid.uuid4())

    assert world.tables.create_locks == [TENANT_A]


# --- Session versions --------------------------------------------------------------------------


class FailingUnitOfWork(FakeUnitOfWork):
    async def commit(self) -> None:
        raise RuntimeError("commit failed")


async def test_regenerating_the_pin_or_deactivating_bumps_the_session_version_and_ends_access(world: World) -> None:
    table = await world.add()

    await world.regenerate().execute(TENANT_A, table.id)
    await world.update().execute(TENANT_A, table.id, name="Terraza 1")
    await world.update().execute(TENANT_A, table.id, is_active=False)
    await world.update().execute(TENANT_A, table.id, is_active=True)

    assert world.tables.tables[table.id].session_version == 3
    assert world.sessions.access_ended == [(table.id, 2), (table.id, 3)]


async def test_access_is_only_ended_once_the_new_session_version_is_committed(world: World) -> None:
    table = await world.add()
    world.uow = FailingUnitOfWork()

    with pytest.raises(RuntimeError):
        await world.regenerate().execute(TENANT_A, table.id)
    with pytest.raises(RuntimeError):
        await world.update().execute(TENANT_A, table.id, is_active=False)

    # Ending access before the commit would reject every new login until the floor expires.
    assert world.sessions.access_ended == []
