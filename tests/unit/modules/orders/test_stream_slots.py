import asyncio
import gc
from collections.abc import AsyncIterator

from app.modules.orders.infrastructure.stream_slots import StreamSlots
from app.shared.infrastructure.config import Settings, get_settings


async def _two_messages() -> AsyncIterator[str]:
    yield "a"
    yield "b"


def test_each_subject_has_its_own_cap_under_the_total() -> None:
    slots = StreamSlots(total=3, per_subject=2, per_tenant=3)

    assert [slots.take("guest-1", "tenant-a") for _ in range(3)] == [None, None, "session"]
    assert slots.take("guest-2", "tenant-a") is None
    assert slots.take("guest-3", "tenant-b") == "server"
    assert slots.open == 3


def test_one_tenant_cannot_take_every_stream() -> None:
    slots = StreamSlots(total=10, per_subject=4, per_tenant=2)

    assert slots.take("guest-1", "tenant-a") is None
    assert slots.take("guest-2", "tenant-a") is None

    assert slots.take("guest-3", "tenant-a") == "server"
    assert slots.open == 2
    # A refused stream takes nothing, and another tenant is not affected.
    assert slots.take("guest-4", "tenant-b") is None
    assert slots.open == 3


def test_the_cap_per_session_is_reported_before_the_cap_per_tenant() -> None:
    slots = StreamSlots(total=10, per_subject=1, per_tenant=1)
    assert slots.take("guest-1", "tenant-a") is None

    assert slots.take("guest-1", "tenant-a") == "session"


def test_the_cap_per_tenant_defaults_to_the_setting() -> None:
    slots = StreamSlots(total=10, per_subject=1)

    assert slots.per_tenant == get_settings().sse_max_streams_per_tenant
    assert Settings.model_fields["sse_max_streams_per_tenant"].default == 200


def test_a_stream_gives_its_slot_back_when_it_ends() -> None:
    slots = StreamSlots(total=1, per_subject=1, per_tenant=1)
    assert slots.take("tablet", "tenant-a") is None

    async def read() -> list[str]:
        return [message async for message in slots.holding("tablet", "tenant-a", _two_messages())]

    assert asyncio.run(read()) == ["a", "b"]
    assert slots.open == 0
    assert slots.take("tablet", "tenant-a") is None


def test_a_tenant_gets_its_slot_back_when_the_stream_fails() -> None:
    async def broken() -> AsyncIterator[str]:
        yield "a"
        raise ConnectionError

    slots = StreamSlots(total=10, per_subject=4, per_tenant=1)
    assert slots.take("tablet", "tenant-a") is None

    async def read() -> None:
        async for _ in slots.holding("tablet", "tenant-a", broken()):
            pass

    try:
        asyncio.run(read())
    except ConnectionError:
        pass

    assert slots.open == 0
    assert slots.take("other", "tenant-a") is None


def test_a_stream_that_never_started_still_gives_its_slot_back() -> None:
    # The client left before the response started streaming: the generator never runs its `finally`.
    slots = StreamSlots(total=1, per_subject=1, per_tenant=1)
    assert slots.take("tablet", "tenant-a") is None

    held = slots.holding("tablet", "tenant-a", _two_messages())
    del held
    gc.collect()

    assert slots.open == 0
    assert slots.take("other", "tenant-a") is None
