"""Request checks that apply to every API route, whatever the module."""

import json
from typing import Any

from fastapi import HTTPException, Request, status

_JSON_METHODS = frozenset({"POST", "PUT", "PATCH"})
NUL_DETAIL = "Text cannot contain NUL characters"
TOO_DEEP_DETAIL = "The request body is nested too deeply"


def _has_nul(payload: Any) -> bool:
    """Iterative walk (no recursion), so no nesting depth can exhaust the stack."""
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if "\x00" in value:
                return True
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return False


async def reject_nul_characters(request: Request) -> None:
    """Postgres text cannot store U+0000; refuse it as a 422 before any work instead of failing with a 500.

    Checks the decoded JSON, so a literal backslash followed by "u0000" stays ordinary text. A body
    that is not valid JSON is left to the route's own validation. A body nested deeper than the JSON
    decoder can handle is refused here too: the route would otherwise fail decoding it with a 500.
    """
    if request.method not in _JSON_METHODS or "json" not in request.headers.get("content-type", ""):
        return
    body = await request.body()
    if not body:
        return
    try:
        payload = json.loads(body)
    except RecursionError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=TOO_DEEP_DETAIL) from None
    except ValueError:
        return
    if _has_nul(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=NUL_DETAIL)
