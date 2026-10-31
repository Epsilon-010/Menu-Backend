"""Keyset (cursor) pagination: a page starts right after the last row of the previous one.

Lists are ordered by a text sort key (e.g. the lowercased name) with the id breaking ties, so a row
added or removed between two requests never makes another row be skipped or shown twice.
"""

import uuid
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_CURSOR_KEY_LENGTH = 256


@dataclass(frozen=True)
class Cursor:
    """Position after a row: its sort key and its id."""

    key: str
    id: uuid.UUID


@dataclass(frozen=True)
class PageRequest:
    limit: int = DEFAULT_PAGE_SIZE
    after: Cursor | None = None


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    # Where the next page starts; None on the last page.
    next: Cursor | None = None
