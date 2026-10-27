"""Request checks that apply to every API route, whatever the module."""

import json
from typing import Any

from fastapi import HTTPException, Request, status

_JSON_METHODS = frozenset({"POST", "PUT", "PATCH"})
NUL_DETAIL = "Text cannot contain NUL characters"


def _has_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(key) or _has_nul(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_nul(item) for item in value)
    return False


async def reject_nul_characters(request: Request) -> None:
    """Postgres text cannot store U+0000; refuse it as a 422 before any work instead of failing with a 500.

    Checks the decoded JSON, so a literal backslash followed by "u0000" stays ordinary text. A body
    that is not valid JSON is left to the route's own validation.
    """
    if request.method not in _JSON_METHODS or "json" not in request.headers.get("content-type", ""):
        return
    body = await request.body()
    if not body:
        return
    try:
        payload = json.loads(body)
    except ValueError:
        return
    if _has_nul(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=NUL_DETAIL)
