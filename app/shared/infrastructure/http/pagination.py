"""HTTP side of cursor pagination: `?limit=&cursor=` in, `{items, next_cursor}` out.

The cursor is opaque to clients (base64url of `[sort key, id]`). Tampering with it only moves where
the page starts: every query stays filtered by the caller's tenant.
"""

import base64
import binascii
import json
import uuid
from collections.abc import Callable
from typing import Annotated, Generic, TypeVar

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.shared.domain.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_CURSOR_KEY_LENGTH,
    MAX_PAGE_SIZE,
    Cursor,
    Page,
    PageRequest,
)

T = TypeVar("T")
Out = TypeVar("Out", bound=BaseModel)

INVALID_CURSOR = "Invalid cursor"
# base64 of the longest key the server makes: each character takes at most 6 bytes in the JSON (a
# control character escaped as a six-character JSON escape), plus the uuid (36) and the punctuation.
_MAX_CURSOR_LENGTH = 4 * -(-(MAX_CURSOR_KEY_LENGTH * 6 + 36 + 8) // 3)


class PageOut(BaseModel, Generic[Out]):
    items: list[Out]
    # Pass it back as `cursor` for the next page; null on the last page.
    next_cursor: str | None


def encode_cursor(cursor: Cursor) -> str:
    raw = json.dumps([cursor.key, str(cursor.id)], ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str) -> Cursor:
    invalid = HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, INVALID_CURSOR)
    if not value or len(value) > _MAX_CURSOR_LENGTH:
        raise invalid
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        key, cursor_id = decoded
        if not isinstance(key, str) or not isinstance(cursor_id, str) or len(key) > MAX_CURSOR_KEY_LENGTH:
            raise ValueError("bad cursor fields")
        # JSON escapes can smuggle text Postgres refuses (a NUL, a lone surrogate): never send it a query.
        if "\x00" in key:
            raise ValueError("NUL in cursor key")
        key.encode("utf-8")
        return Cursor(key=key, id=uuid.UUID(cursor_id))
    except (binascii.Error, UnicodeError, ValueError, TypeError) as error:
        raise invalid from error


def _page_request(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> PageRequest:
    return PageRequest(limit=limit, after=decode_cursor(cursor) if cursor is not None else None)


PageQuery = Annotated[PageRequest, Depends(_page_request)]


def page_out(page: Page[T], convert: Callable[[T], Out]) -> PageOut[Out]:
    return PageOut(
        items=[convert(item) for item in page.items],
        next_cursor=encode_cursor(page.next) if page.next is not None else None,
    )
