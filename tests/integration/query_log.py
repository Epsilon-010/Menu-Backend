"""Records the SQL a block of test code really sends, to pin the shape of a query path."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


@contextmanager
def recorded_statements() -> Iterator[list[str]]:
    """Every statement any engine of this process runs inside the block (the app's included)."""
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)
