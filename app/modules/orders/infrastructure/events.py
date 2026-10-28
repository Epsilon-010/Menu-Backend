"""Server-Sent Events for a table: everyone at it hears that the cart or its orders changed.

Events carry no data beyond their kind and the new cart version; the client reloads from the API,
which is the source of truth (and re-checks the visit). A stream lasts at most a few minutes, so a
guest whose visit ended is cut off on the next reconnect, when their session is checked again.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.orders.infrastructure.adapters import table_events_stream

logger = logging.getLogger(__name__)

BLOCK_MS = 15_000
STREAM_SECONDS = 300.0
# Ends a guest's stream: their visit is over (the client then finds its session ended).
_CLOSING_KINDS = frozenset({"bill.closed"})


async def _latest_id(redis: Redis, stream: str) -> str:
    """The id of the stream's newest entry ("0-0" when empty). Reading after a concrete id instead of "$"
    never loses an event published between two reads, or while Redis was briefly unreachable."""
    newest = await redis.xrevrange(stream, count=1)
    return str(newest[0][0]) if newest else "0-0"


def _message(event_id: str, kind: str, data: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(data)}\n\n"


async def table_events(
    redis: Redis,
    tenant_id: uuid.UUID,
    table_id: uuid.UUID,
    last_event_id: str | None,
    *,
    stop_on_close: bool,
) -> AsyncIterator[str]:
    """Yields the SSE messages of one table from its tenant's stream, starting after `last_event_id`
    (or from now), for STREAM_SECONDS; a comment every BLOCK_MS keeps proxies from closing an idle one."""
    stream = table_events_stream(tenant_id)
    cursor = last_event_id
    block_ms = BLOCK_MS
    deadline = time.monotonic() + STREAM_SECONDS
    failing = False
    # Tells the browser to wait this long before reconnecting after the stream ends.
    yield "retry: 2000\n\n"
    while time.monotonic() < deadline:
        try:
            if cursor is None:
                cursor = await _latest_id(redis, stream)
            batches = await redis.xread({stream: cursor}, block=block_ms, count=100)
        except RedisError:
            # One warning per outage, not one every retry of every open stream.
            if not failing:
                logger.warning("Could not read the events of table %s", table_id, exc_info=True)
            failing = True
            await asyncio.sleep(2)
            yield ": reconnecting\n\n"
            continue
        failing = False
        if not batches:
            yield ": keep-alive\n\n"
            continue
        for _stream, entries in batches:
            for event_id, fields in entries:
                cursor = event_id
                if fields.get("table_id") != str(table_id):
                    continue
                kind = fields.get("kind", "changed")
                data: dict[str, object] = {}
                if "cart_version" in fields:
                    data["cart_version"] = int(fields["cart_version"])
                yield _message(event_id, kind, data)
                if stop_on_close and kind in _CLOSING_KINDS:
                    return
