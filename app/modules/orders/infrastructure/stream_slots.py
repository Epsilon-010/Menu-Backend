"""How many live-update streams (SSE) may be open at once, per session, per tenant and in total.

Every open stream holds a Redis connection of its own pool while it waits for events, so without a cap
one client (or a busy venue) could open streams until that pool runs dry, and one tenant could take every
stream of the server from the others. The counts live in this API process: each process has its own pool
and its own caps.
"""

from collections import Counter
from collections.abc import AsyncIterator
from typing import Literal

from app.shared.infrastructure.config import get_settings

Refusal = Literal["session", "server"]


class StreamSlots:
    def __init__(self, total: int, per_subject: int, per_tenant: int | None = None) -> None:
        self.total = total
        self.per_subject = per_subject
        self.per_tenant = get_settings().sse_max_streams_per_tenant if per_tenant is None else per_tenant
        self.open = 0
        self._by_subject: Counter[str] = Counter()
        self._by_tenant: Counter[str] = Counter()

    def take(self, subject: str, tenant: str) -> Refusal | None:
        """Takes a slot for one more stream of `subject` (the account, table or guest) of `tenant`; None when
        granted. A tenant at its cap is refused like a full server: nothing it can do frees a slot right now."""
        if self._by_subject[subject] >= self.per_subject:
            return "session"
        if self._by_tenant[tenant] >= self.per_tenant or self.open >= self.total:
            return "server"
        self._by_subject[subject] += 1
        self._by_tenant[tenant] += 1
        self.open += 1
        return None

    def give_back(self, subject: str, tenant: str) -> None:
        for counts, key in ((self._by_subject, subject), (self._by_tenant, tenant)):
            counts[key] -= 1
            if counts[key] <= 0:
                del counts[key]
        self.open -= 1

    def holding(self, subject: str, tenant: str, events: AsyncIterator[str]) -> "HeldStream":
        """Streams `events` and gives the slot back when the stream ends, fails or the client leaves."""
        return HeldStream(self, subject, tenant, events)


class HeldStream:
    """The events of one stream plus its slot. The slot also comes back if the response is dropped
    before the stream ever starts (a generator that never ran never reaches its `finally`)."""

    def __init__(self, slots: StreamSlots, subject: str, tenant: str, events: AsyncIterator[str]) -> None:
        self._slots = slots
        self._subject = subject
        self._tenant = tenant
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
            self._slots.give_back(self._subject, self._tenant)

    def __del__(self) -> None:
        self.release()
