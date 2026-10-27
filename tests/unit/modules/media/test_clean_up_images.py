import uuid
from datetime import timedelta

import pytest

from app.modules.media.application.clean_up_images import CleanUpImages
from tests.unit.fakes import FakeClock, FakeImageStorage, FakeUnitOfWork, InMemoryImageRegistry

pytestmark = pytest.mark.anyio

TENANT = uuid.uuid4()
TTL = timedelta(minutes=60)


class World:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.registry = InMemoryImageRegistry(self.clock)
        self.storage = FakeImageStorage()
        self.uow = FakeUnitOfWork()

    def clean_up(self, batch_size: int = 50) -> CleanUpImages:
        return CleanUpImages(self.registry, self.storage, self.clock, self.uow, pending_ttl=TTL, batch_size=batch_size)

    async def image(self, name: str, status: str = "pending") -> str:
        public_id = f"tenants/{TENANT}/items/{name}"
        self.storage.upload(public_id)
        await self.registry.register(TENANT, public_id)
        if status in ("attached", "discarded"):
            await self.registry.attach(TENANT, public_id)
        if status == "discarded":
            await self.registry.discard(TENANT, public_id)
        return public_id


@pytest.fixture
def world() -> World:
    return World()


async def test_deletes_discarded_images_and_forgets_them(world: World) -> None:
    old = await world.image("old", "discarded")
    used = await world.image("used", "attached")

    result = await world.clean_up().execute()

    assert (result.deleted, result.failed) == (1, 0)
    assert world.storage.deleted == [old]
    assert world.registry.status(old) is None
    assert world.registry.status(used) == "attached"
    assert world.uow.commits == 1


async def test_deletes_pending_uploads_only_after_the_ttl(world: World) -> None:
    abandoned = await world.image("abandoned")
    world.clock.advance(TTL + timedelta(seconds=1))
    fresh = await world.image("fresh")

    await world.clean_up().execute()

    # The fresh one may still be attached by the admin who is uploading it right now.
    assert world.storage.deleted == [abandoned]
    assert world.registry.status(fresh) == "pending"


async def test_a_failed_delete_keeps_the_record_for_the_next_run(world: World) -> None:
    discarded = await world.image("discarded", "discarded")
    world.storage.fail_deletes = True

    failed = await world.clean_up().execute()
    world.storage.fail_deletes = False
    retried = await world.clean_up().execute()

    assert (failed.deleted, failed.failed) == (0, 1)
    assert (retried.deleted, retried.failed) == (1, 0)
    assert world.registry.status(discarded) is None


async def test_handles_one_batch_per_run(world: World) -> None:
    for index in range(3):
        await world.image(f"img{index}", "discarded")

    first = await world.clean_up(batch_size=2).execute()
    second = await world.clean_up(batch_size=2).execute()

    assert (first.deleted, second.deleted) == (2, 1)
    assert world.registry.records == {}
