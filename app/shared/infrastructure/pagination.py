"""Keyset pagination of a SQLAlchemy select: `WHERE (key, id) > cursor ORDER BY key, id LIMIT n + 1`."""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, String, Uuid, literal, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.domain.pagination import Cursor, PageRequest


async def keyset_page(
    session: AsyncSession,
    statement: Select[Any],
    key: ColumnElement[str],
    id_column: ColumnElement[uuid.UUID],
    request: PageRequest,
) -> tuple[list[Any], Cursor | None]:
    """`statement` selects one model, already filtered (by tenant first) and not ordered.

    Returns the page's models and the cursor of the next page (None on the last one): one extra row
    is read to know whether there is a next page without a count query.
    """
    paged = statement.add_columns(key.label("sort_key"))
    if request.after is not None:
        after = tuple_(literal(request.after.key, String()), literal(request.after.id, Uuid()))
        paged = paged.where(tuple_(key, id_column) > after)
    rows = (await session.execute(paged.order_by(key, id_column).limit(request.limit + 1))).all()
    has_more = len(rows) > request.limit
    rows = rows[: request.limit]
    following = Cursor(key=rows[-1].sort_key, id=rows[-1][0].id) if has_more else None
    return [row[0] for row in rows], following
