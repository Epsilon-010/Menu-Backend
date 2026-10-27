"""Every error response of the API is an RFC 9457 problem document (application/problem+json)."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import _seed, login

PROBLEM_JSON = "application/problem+json"


def problem(status: int, title: str, detail: str | None = None, **extensions: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    return {**body, **extensions}


def assert_problem(response: Response, expected: dict[str, Any]) -> None:
    assert response.status_code == expected["status"]
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json() == expected


@pytest.fixture
def tenant_a() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


@pytest.fixture
def admin(client: TestClient, tenant_a: SeedResult) -> TestClient:
    assert login(client).status_code == 200
    return client


def test_missing_session_is_a_401_problem(client: TestClient) -> None:
    assert_problem(client.get("/api/v1/auth/me"), problem(401, "Unauthorized", "Not authenticated"))


def test_wrong_role_is_a_403_problem(client: TestClient, tenant_a: SeedResult) -> None:
    from tests.integration.modules.auth.test_auth_api import claims_for, sign

    client.cookies.set("access_token", sign(claims_for(tenant_a.user_id, tenant_a.tenant_id, "waiter")))

    assert_problem(client.get("/api/v1/tables"), problem(403, "Forbidden", "Not allowed"))


def test_unknown_route_and_wrong_method_are_problems(client: TestClient) -> None:
    assert_problem(client.get("/api/v1/nope"), problem(404, "Not Found"))
    assert_problem(client.delete("/api/v1/auth/login"), problem(405, "Method Not Allowed"))


def test_domain_errors_keep_their_message_as_detail(admin: TestClient) -> None:
    assert admin.post("/api/v1/tables", json={"name": "Mesa 4"}).status_code == 201

    assert_problem(
        admin.post("/api/v1/tables", json={"name": "mesa 4"}),
        problem(409, "Conflict", "Table name already in use"),
    )
    assert_problem(
        admin.post("/api/v1/tables", json={"name": "   "}),
        problem(422, "Unprocessable Content", "Table name must have 1 to 60 characters"),
    )
    assert_problem(
        admin.patch("/api/v1/tables/00000000-0000-0000-0000-000000000000", json={"is_active": False}),
        problem(404, "Not Found", "Table not found"),
    )


def test_request_validation_lists_the_errors_without_echoing_the_input(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"username": "ab", "password": "super-secret-value"})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert {key: body[key] for key in ("type", "title", "status")} == {
        "type": "about:blank",
        "title": "Unprocessable Content",
        "status": 422,
    }
    assert body["errors"] == [
        {"loc": ["body", "username"], "msg": "String should have at least 3 characters", "type": "string_too_short"}
    ]
    assert "super-secret-value" not in response.text
    assert "detail" not in body


def test_rate_limited_login_is_a_429_problem_with_retry_after(client: TestClient, tenant_a: SeedResult) -> None:
    from app.shared.infrastructure.config import get_settings

    for _ in range(get_settings().login_max_failures_per_account):
        login(client, password="wrong-pass")

    response = login(client, password="wrong-pass")

    assert_problem(response, problem(429, "Too Many Requests", "Too many login attempts. Try again later."))
    assert int(response.headers["retry-after"]) > 0


@pytest.fixture
def failing_client() -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app()

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as test_client:
        yield test_client


def test_unhandled_errors_are_a_500_problem_that_leaks_nothing(failing_client: TestClient) -> None:
    response = failing_client.get("/api/v1/boom")

    assert_problem(response, problem(500, "Internal Server Error"))
    assert "hunter2" not in response.text
