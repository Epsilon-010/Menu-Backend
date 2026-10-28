import uuid
from datetime import timedelta

import pytest

from app.modules.media.application.clean_up_images import CleanUpImages, retry_delay
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


async def test_a_failed_delete_is_retried_later_with_a_growing_delay(world: World) -> None:
    discarded = await world.image("discarded", "discarded")
    world.storage.fail_deletes = True

    failed = await world.clean_up().execute()
    right_after = await world.clean_up().execute()
    world.clock.advance(retry_delay(1))
    world.storage.fail_deletes = False
    retried = await world.clean_up().execute()

    assert (failed.deleted, failed.failed) == (0, 1)
    # Postponed: an image that keeps failing does not take a place in every run.
    assert (right_after.deleted, right_after.failed) == (0, 0)
    assert (retried.deleted, retried.failed) == (1, 0)
    assert world.registry.status(discarded) is None


async def test_a_failing_image_never_blocks_the_others(world: World) -> None:
    broken = await world.image("broken", "discarded")
    healthy = await world.image("healthy", "discarded")
    world.storage.fail_deletes_for = {broken}

    first = await world.clean_up(batch_size=1).execute()
    second = await world.clean_up(batch_size=1).execute()

    assert (first.failed, second.deleted) == (1, 1)
    assert world.storage.deleted == [healthy]
    assert world.registry.status(broken) == "discarded"


def test_retry_delay_doubles_up_to_six_hours() -> None:
    assert [retry_delay(attempt) for attempt in (1, 2, 3)] == [
        timedelta(minutes=2),
        timedelta(minutes=4),
        timedelta(minutes=8),
    ]
    assert retry_delay(30) == timedelta(hours=6)


async def test_handles_one_batch_per_run(world: World) -> None:
    for index in range(3):
        await world.image(f"img{index}", "discarded")

    first = await world.clean_up(batch_size=2).execute()
    second = await world.clean_up(batch_size=2).execute()

    assert (first.deleted, second.deleted) == (2, 1)
    assert world.registry.records == {}
