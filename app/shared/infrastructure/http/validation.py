"""Request checks that apply to every API route, whatever the module."""

import json
from typing import Any

from fastapi import HTTPException, Request, status

_JSON_METHODS = frozenset({"POST", "PUT", "PATCH"})
NUL_DETAIL = "Text cannot contain NUL characters"
SURROGATE_DETAIL = "Text cannot contain invalid Unicode characters"


def _is_encodable(text: str) -> bool:
    """False for a lone surrogate: it decodes from a JSON escape but has no UTF-8 form to store or send."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _unstorable_text(payload: Any) -> str | None:
    """The problem to report, if some text in the payload could not be stored.

    Iterative walk (no recursion), so no nesting depth can exhaust the stack.
    """
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if "\x00" in value:
                return NUL_DETAIL
            if not _is_encodable(value):
                return SURROGATE_DETAIL
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return None


async def reject_nul_characters(request: Request) -> None:
    """Text Postgres cannot store (U+0000) or nothing can encode (a lone surrogate, "\ud800") is refused
    as a 422 before any work, instead of failing later with a 500.

    Checks the decoded JSON, so a literal backslash followed by "u0000" stays ordinary text. A body
    that is not valid JSON is left to the route's own validation. FastAPI decodes the body before any
    dependency runs, so a body too deep to decode never reaches this check (it is a 400 problem).
    """
    if request.method not in _JSON_METHODS or "json" not in request.headers.get("content-type", ""):
        return
    body = await request.body()
    if not body:
        return
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        # Not JSON, or nested deeper than the decoder goes (routes without a body never decode it).
        return
    detail = _unstorable_text(payload)
    if detail is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
