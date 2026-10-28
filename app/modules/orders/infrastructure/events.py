"""Server-Sent Events from the tenant's order stream (`orders:{tenant_id}`).

A table hears that its cart or its orders changed; the staff hear that orders and bills changed. Events
carry no data beyond their kind and a few ids (never prices); clients reload from the API, which is the
source of truth (and re-checks who may see what). A stream lasts at most a few minutes, so a session
that ended is cut off on the next reconnect, when it is checked again.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.orders.infrastructure.adapters import table_events_stream

logger = logging.getLogger(__name__)

BLOCK_MS = 15_000
STREAM_SECONDS = 300.0
# Ends a guest's stream: their visit is over (the client then finds its session ended).
_CLOSING_KINDS = frozenset({"bill.closed"})
# What the staff hear: never cart changes (they belong to the table) and never prices.
STAFF_KINDS = frozenset({"order.created", "order.updated", "bill.opened", "bill.closed"})

# Turns a stream entry into the (event, data) to send, or None to skip it.
Selector = Callable[[dict[str, str]], tuple[str, dict[str, object]] | None]


async def _latest_id(redis: Redis, stream: str) -> str:
    """The id of the stream's newest entry ("0-0" when empty). Reading after a concrete id instead of "$"
    never loses an event published between two reads, or while Redis was briefly unreachable."""
    newest = await redis.xrevrange(stream, count=1)
    return str(newest[0][0]) if newest else "0-0"


def _message(event_id: str, kind: str, data: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(data)}\n\n"


async def _events(
    redis: Redis,
    tenant_id: uuid.UUID,
    last_event_id: str | None,
    select: Selector,
    *,
    who: str,
    stop_on_close: bool = False,
) -> AsyncIterator[str]:
    """Yields the selected SSE messages of the tenant's stream, starting after `last_event_id` (or from
    now), for STREAM_SECONDS; a comment every BLOCK_MS keeps proxies from closing an idle one."""
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
                logger.warning("Could not read the events of %s", who, exc_info=True)
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
                selected = select(fields)
                if selected is None:
                    continue
                kind, data = selected
                yield _message(event_id, kind, data)
                if stop_on_close and kind in _CLOSING_KINDS:
                    return


def table_events(
    redis: Redis,
    tenant_id: uuid.UUID,
    table_id: uuid.UUID,
    last_event_id: str | None,
    *,
    stop_on_close: bool,
) -> AsyncIterator[str]:
    """Every event of one table (cart, orders, bill), with the new cart version when there is one."""

    def select(fields: dict[str, str]) -> tuple[str, dict[str, object]] | None:
        if fields.get("table_id") != str(table_id):
            return None
        data: dict[str, object] = {}
        if "cart_version" in fields:
            data["cart_version"] = int(fields["cart_version"])
        return fields.get("kind", "changed"), data

    return _events(
        redis, tenant_id, last_event_id, select, who=f"table {table_id}", stop_on_close=stop_on_close
    )


def staff_events(redis: Redis, tenant_id: uuid.UUID, last_event_id: str | None) -> AsyncIterator[str]:
    """Order and bill events of every table of the tenant, with the table (and order) they concern."""

    def select(fields: dict[str, str]) -> tuple[str, dict[str, object]] | None:
        kind = fields.get("kind", "")
        if kind not in STAFF_KINDS or "table_id" not in fields:
            return None
        data: dict[str, object] = {"table_id": fields["table_id"]}
        if "order_id" in fields:
            data["order_id"] = fields["order_id"]
        return kind, data

    return _events(redis, tenant_id, last_event_id, select, who=f"the staff of tenant {tenant_id}")
