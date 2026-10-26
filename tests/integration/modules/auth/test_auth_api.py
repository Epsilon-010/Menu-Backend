import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from httpx import Response
from jose import jwt

from app.seed import SeedResult, seed_tenant
from app.shared.domain.principal import Principal, Role
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from app.shared.infrastructure.http.auth import require_role

PASSWORD = "s3cret-pass"
GENERIC_LOGIN_ERROR = {"detail": "Invalid email or password"}


async def _seed(tenant: str, email: str) -> SeedResult:
    engine = create_engine(get_settings().database_url)
    try:
        return await seed_tenant(create_session_factory(engine), tenant, email, "Owner", PASSWORD)
    finally:
        await engine.dispose()


@pytest.fixture
def tenant_a() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


@pytest.fixture
def tenant_b() -> SeedResult:
    return asyncio.run(_seed("Burger Place", "boss@example.com"))


def login(client: TestClient, email: str = "owner@example.com", password: str = PASSWORD) -> Response:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def refresh_with(client: TestClient, token: str | None) -> Response:
    """Sends exactly the given refresh cookie, ignoring whatever the client jar holds."""
    client.cookies.clear()
    headers = {"Cookie": f"refresh_token={token}"} if token is not None else {}
    return client.post("/api/v1/auth/refresh", headers=headers)


def me(client: TestClient, access_token: str) -> Response:
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})


def sign(claims: dict[str, Any], secret: str | None = None) -> str:
    key = secret or get_settings().jwt_secret.get_secret_value()
    return jwt.encode(claims, key, algorithm="HS256")


def claims_for(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str = "admin", **extra: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=15),
        **extra,
    }


# --- Login -------------------------------------------------------------------------------------


def test_login_returns_a_15_minute_access_token_and_a_hardened_refresh_cookie(
    client: TestClient, tenant_a: SeedResult
) -> None:
    response = login(client, email="OWNER@example.com")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["role"] == "admin"
    claims = jwt.decode(body["access_token"], get_settings().jwt_secret.get_secret_value(), algorithms=["HS256"])
    assert claims["sub"] == str(tenant_a.user_id)
    assert claims["tenant_id"] == str(tenant_a.tenant_id)
    assert claims["role"] == "admin"
    assert claims["exp"] - claims["iat"] == 900
    assert uuid.UUID(claims["jti"])
    assert "table_id" not in claims

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("refresh_token=")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "Max-Age=604800" in cookie


def test_wrong_password_and_unknown_email_get_the_same_generic_error(client: TestClient, tenant_a: SeedResult) -> None:
    wrong_password = login(client, password="wrong-pass")
    unknown_email = login(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == GENERIC_LOGIN_ERROR
    assert "set-cookie" not in wrong_password.headers


def test_too_many_failures_for_an_account_block_it_temporarily(client: TestClient, tenant_a: SeedResult) -> None:
    for _ in range(get_settings().login_max_failures_per_account):
        assert login(client, password="wrong-pass").status_code == 401

    blocked = login(client)

    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many login attempts. Try again later."}
    assert 0 < int(blocked.headers["retry-after"]) <= get_settings().login_failure_window_seconds


def test_too_many_failures_from_one_ip_block_every_account(client: TestClient, tenant_a: SeedResult) -> None:
    for attempt in range(get_settings().login_max_failures_per_ip):
        assert login(client, email=f"guess-{attempt}@example.com").status_code == 401

    assert login(client).status_code == 429


def test_a_successful_login_clears_the_account_failures(client: TestClient, tenant_a: SeedResult) -> None:
    for _ in range(get_settings().login_max_failures_per_account - 1):
        login(client, password="wrong-pass")
    assert login(client).status_code == 200

    for _ in range(get_settings().login_max_failures_per_account - 1):
        assert login(client, password="wrong-pass").status_code == 401
    assert login(client).status_code == 200


@pytest.mark.parametrize("body", [{}, {"email": "owner@example.com"}, {"email": "x" * 300, "password": PASSWORD}])
def test_login_validates_the_body(client: TestClient, body: dict[str, str]) -> None:
    assert client.post("/api/v1/auth/login", json=body).status_code == 422


# --- Me ----------------------------------------------------------------------------------------


def test_me_returns_the_admin_and_the_business_name(client: TestClient, tenant_a: SeedResult) -> None:
    access_token = login(client).json()["access_token"]

    response = me(client, access_token)

    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": str(tenant_a.user_id), "email": "owner@example.com", "full_name": "Owner", "role": "admin"},
        "tenant": {"id": str(tenant_a.tenant_id), "name": "La Taquería"},
    }


def test_a_token_from_one_tenant_cannot_reach_another_tenants_data(
    client: TestClient, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    # A validly signed token that pairs tenant A's user with tenant B must find nothing.
    forged = sign(claims_for(tenant_a.user_id, tenant_b.tenant_id))

    assert me(client, forged).status_code == 401
    a = me(client, login(client).json()["access_token"]).json()
    b = me(client, login(client, email="boss@example.com").json()["access_token"]).json()
    assert a["tenant"]["name"] == "La Taquería"
    assert b["tenant"]["name"] == "Burger Place"


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        "expired",
        "wrong-secret",
        "missing-tenant",
        "unknown-role",
    ],
)
def test_me_rejects_invalid_access_tokens(client: TestClient, tenant_a: SeedResult, token: str) -> None:
    base = claims_for(tenant_a.user_id, tenant_a.tenant_id)
    tokens = {
        "not-a-jwt": "not-a-jwt",
        "expired": sign({**base, "exp": datetime.now(UTC) - timedelta(seconds=1)}),
        "wrong-secret": sign(base, secret="another-secret-that-is-at-least-32-characters"),
        "missing-tenant": sign({k: v for k, v in base.items() if k != "tenant_id"}),
        "unknown-role": sign({**base, "role": "superuser"}),
    }

    response = me(client, tokens[token])

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


# --- Refresh -----------------------------------------------------------------------------------


def test_refresh_rotates_the_token_and_the_previous_one_stops_working(client: TestClient, tenant_a: SeedResult) -> None:
    first = login(client).cookies["refresh_token"]

    rotated = refresh_with(client, first)

    assert rotated.status_code == 200
    assert rotated.json()["role"] == "admin"
    second = rotated.cookies["refresh_token"]
    assert second != first
    assert me(client, rotated.json()["access_token"]).status_code == 200


def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(client: TestClient, tenant_a: SeedResult) -> None:
    first = login(client).cookies["refresh_token"]
    second = refresh_with(client, first).cookies["refresh_token"]

    reused = refresh_with(client, first)

    assert reused.status_code == 401
    assert 'refresh_token=""' in reused.headers["set-cookie"]
    assert refresh_with(client, second).status_code == 401


def test_refresh_without_a_cookie_is_rejected(client: TestClient) -> None:
    assert refresh_with(client, None).status_code == 401
    assert refresh_with(client, "never-issued").status_code == 401


# --- Logout ------------------------------------------------------------------------------------


def test_logout_revokes_the_session_and_clears_the_cookie(client: TestClient, tenant_a: SeedResult) -> None:
    token = login(client).cookies["refresh_token"]

    client.cookies.clear()
    response = client.post("/api/v1/auth/logout", headers={"Cookie": f"refresh_token={token}"})

    assert response.status_code == 204
    assert 'refresh_token=""' in response.headers["set-cookie"]
    assert refresh_with(client, token).status_code == 401


def test_logout_without_a_session_still_succeeds(client: TestClient) -> None:
    assert client.post("/api/v1/auth/logout").status_code == 204


# --- require_role ------------------------------------------------------------------------------


@pytest.fixture
def guarded_client(client: TestClient) -> TestClient:
    @client.app.get("/test/admin-only")  # type: ignore[attr-defined]
    async def admin_only(principal: Principal = Depends(require_role("admin"))) -> dict[str, str]:
        return {"tenant_id": str(principal.tenant_id)}

    return client


@pytest.mark.parametrize(("role", "status"), [("admin", 200), ("waiter", 403), ("kitchen", 403), ("table", 403)])
def test_require_role_only_lets_the_listed_roles_through(guarded_client: TestClient, role: str, status: int) -> None:
    tenant_id = uuid.uuid4()
    extra = {"table_id": str(uuid.uuid4())} if role == "table" else {}
    token = sign(claims_for(uuid.uuid4(), tenant_id, role=role, **extra))

    response = guarded_client.get("/test/admin-only", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == status
    if status == 200:
        assert response.json() == {"tenant_id": str(tenant_id)}


def test_require_role_rejects_anonymous_callers(guarded_client: TestClient) -> None:
    assert guarded_client.get("/test/admin-only").status_code == 401


def test_require_role_refuses_unknown_roles_at_definition_time() -> None:
    with pytest.raises(ValueError):
        require_role("superuser")


def test_table_principal_keeps_its_table_id(guarded_client: TestClient) -> None:
    table_id = uuid.uuid4()
    token = sign(claims_for(uuid.uuid4(), uuid.uuid4(), role="table", table_id=str(table_id)))
    decoded = guarded_client.app.state.access_tokens.decode(token)  # type: ignore[attr-defined]

    assert decoded.role is Role.TABLE
    assert decoded.table_id == table_id
