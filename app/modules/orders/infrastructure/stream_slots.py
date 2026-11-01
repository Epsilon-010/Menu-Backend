"""How many live-update streams (SSE) may be open at once, per session and in total.

Every open stream holds a Redis connection of its own pool while it waits for events, so without a cap
one client (or a busy venue) could open streams until that pool runs dry. The counts live in this API
process: each process has its own pool and its own caps.
"""

from collections import Counter
from collections.abc import AsyncIterator
from typing import Literal

Refusal = Literal["session", "server"]


class StreamSlots:
    def __init__(self, total: int, per_subject: int) -> None:
        self.total = total
        self.per_subject = per_subject
        self.open = 0
        self._by_subject: Counter[str] = Counter()

    def take(self, subject: str) -> Refusal | None:
        """Takes a slot for one more stream of `subject` (the account, table or guest); None when granted."""
        if self._by_subject[subject] >= self.per_subject:
            return "session"
        if self.open >= self.total:
            return "server"
        self._by_subject[subject] += 1
        self.open += 1
        return None

    def give_back(self, subject: str) -> None:
        self._by_subject[subject] -= 1
        if self._by_subject[subject] <= 0:
            del self._by_subject[subject]
        self.open -= 1

    def holding(self, subject: str, events: AsyncIterator[str]) -> "HeldStream":
        """Streams `events` and gives the slot back when the stream ends, fails or the client leaves."""
        return HeldStream(self, subject, events)


class HeldStream:
    """The events of one stream plus its slot. The slot also comes back if the response is dropped
    before the stream ever starts (a generator that never ran never reaches its `finally`)."""

    def __init__(self, slots: StreamSlots, subject: str, events: AsyncIterator[str]) -> None:
        self._slots = slots
        self._subject = subject
        self._events = events
        self._held = True

    def __aiter__(self) -> AsyncIterator[str]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[str]:
        try:
            async for message in self._events:
                yield message
        finally:
            self.release()

    def release(self) -> None:
        if self._held:
            self._held = False
            self._slots.give_back(self._subject)

    def __del__(self) -> None:
        self.release()
