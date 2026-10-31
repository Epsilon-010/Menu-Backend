import asyncio
import gc
from collections.abc import AsyncIterator

from app.modules.orders.infrastructure.stream_slots import StreamSlots


async def _two_messages() -> AsyncIterator[str]:
    yield "a"
    yield "b"


def test_each_subject_has_its_own_cap_under_the_total() -> None:
    slots = StreamSlots(total=3, per_subject=2)

    assert [slots.take("guest-1") for _ in range(3)] == [None, None, "session"]
    assert slots.take("guest-2") is None
    assert slots.take("guest-3") == "server"
    assert slots.open == 3


def test_a_stream_gives_its_slot_back_when_it_ends() -> None:
    slots = StreamSlots(total=1, per_subject=1)
    assert slots.take("tablet") is None

    async def read() -> list[str]:
        return [message async for message in slots.holding("tablet", _two_messages())]

    assert asyncio.run(read()) == ["a", "b"]
    assert slots.open == 0
    assert slots.take("tablet") is None


def test_a_stream_that_never_started_still_gives_its_slot_back() -> None:
    # The client left before the response started streaming: the generator never runs its `finally`.
    slots = StreamSlots(total=1, per_subject=1)
    assert slots.take("tablet") is None

    held = slots.holding("tablet", _two_messages())
    del held
    gc.collect()

    assert slots.open == 0
