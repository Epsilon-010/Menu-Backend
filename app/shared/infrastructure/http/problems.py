"""RFC 9457 Problem Details: the body of every error response of the API.

Routers answer expected errors with `problem(status, detail)`; the handlers registered here turn
everything else (HTTPException from the auth dependencies, unknown routes, request validation,
unhandled exceptions) into the same `application/problem+json` document. `detail` is always a
human-readable string; validation problems list `errors` instead and never echo the input.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
# RFC 9110 renamed these; Python's HTTPStatus still has the RFC 7231 phrases.
_RFC_9110_PHRASES = {413: "Content Too Large", 422: "Unprocessable Content"}


def _title(status_code: int) -> str:
    return _RFC_9110_PHRASES.get(status_code) or HTTPStatus(status_code).phrase


def problem(
    status_code: int, detail: str | None = None, *, headers: Mapping[str, str] | None = None, **extensions: Any
) -> JSONResponse:
    """`type` stays "about:blank", so `title` is the HTTP status phrase (RFC 9457, section 4.2.1)."""
    body: dict[str, Any] = {"type": "about:blank", "title": _title(status_code), "status": status_code}
    if detail is not None:
        body["detail"] = detail
    body.update(extensions)
    return JSONResponse(body, status_code=status_code, headers=dict(headers or {}), media_type=PROBLEM_JSON)


async def _http_exception(_: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, StarletteHTTPException):
        raise error
    # Starlette fills an empty detail with the status phrase; repeating the title adds nothing.
    phrases = {_title(error.status_code), HTTPStatus(error.status_code).phrase}
    detail = error.detail if isinstance(error.detail, str) and error.detail not in phrases else None
    return problem(error.status_code, detail, headers=error.headers)


async def _validation_error(_: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    # Only where and why: the rejected input may hold a password or a PIN.
    errors = [{"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]} for item in error.errors()]
    return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, errors=errors)


async def _unhandled_error(request: Request, error: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
    return problem(status.HTTP_500_INTERNAL_SERVER_ERROR)


def register_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
