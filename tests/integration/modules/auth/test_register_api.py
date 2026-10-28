"""S1 self sign-up: a business owner creates the business and its admin in one request and is signed in."""

import asyncio
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select

from app.modules.staff.infrastructure.models import UserModel
from app.modules.tenants.infrastructure.models import TenantModel
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import PASSWORD, _seed, claims_for, login, set_cookies, sign

REGISTER_URL = "/api/v1/auth/register"
EMAIL = "founder@example.com"

ClientFactory = Callable[[], TestClient]


@pytest.fixture
def new_client() -> Iterator[ClientFactory]:
    from app.main import create_app

    with ExitStack() as stack:
        yield lambda: stack.enter_context(TestClient(create_app(), base_url="https://testserver"))


def register(client: TestClient, **fields: Any) -> Response:
    body = {"email": EMAIL, "password": PASSWORD, "business_name": "Tacos El Güero", **fields}
    return client.post(REGISTER_URL, json=body)


def counts() -> tuple[int, int]:
    """Tenants and users in the database: proves a refused sign-up left nothing behind."""

    async def run() -> tuple[int, int]:
        engine = create_engine(get_settings().database_url)
        try:
            async with create_session_factory(engine)() as session:
                tenants = await session.scalar(select(func.count()).select_from(TenantModel))
                users = await session.scalar(select(func.count()).select_from(UserModel))
                return int(tenants or 0), int(users or 0)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_signing_up_creates_the_business_and_its_admin_and_signs_in(new_client: ClientFactory) -> None:
    client = new_client()

    response = register(client, email=" Founder@Example.com ", business_name=" Tacos El Güero ")

    assert response.status_code == 201
    assert response.json() == {"expires_in": 900, "role": "admin"}
    cookies = set_cookies(response)
    assert "HttpOnly" in cookies["access_token"] and "Path=/api" in cookies["access_token"]
    assert "HttpOnly" in cookies["refresh_token"] and "Path=/api/v1/auth" in cookies["refresh_token"]
    assert f"Max-Age={7 * 24 * 3600}" in cookies["refresh_token"]
    account = client.get("/api/v1/auth/me").json()
    assert account["user"]["email"] == EMAIL
    assert account["user"]["full_name"] == "Admin"
    assert account["user"]["role"] == "admin"
    assert account["tenant"]["name"] == "Tacos El Güero"
    # The new business starts empty, and the new admin can manage it right away.
    assert client.get("/api/v1/staff").json() == []
    assert client.post("/api/v1/staff", json={"full_name": "Cook 1", "role": "kitchen"}).status_code == 201
    # The account signs in later like any admin.
    assert login(new_client(), username=EMAIL, password=PASSWORD).status_code == 200
    assert counts() == (1, 2)


def test_a_new_business_never_sees_another_tenants_staff(new_client: ClientFactory) -> None:
    other: SeedResult = asyncio.run(_seed("La Taquería", "owner@example.com"))
    other_admin = new_client()
    assert login(other_admin, username="owner@example.com").status_code == 200
    member = other_admin.post("/api/v1/staff", json={"full_name": "Guest 1", "role": "waiter"}).json()

    client = new_client()
    assert register(client).status_code == 201

    assert client.get("/api/v1/auth/me").json()["tenant"]["id"] != str(other.tenant_id)
    assert client.get("/api/v1/staff").json() == []
    assert client.patch(f"/api/v1/staff/{member['id']}", json={"is_active": False}).status_code == 404
    assert client.post(f"/api/v1/staff/{member['id']}/pin").status_code == 404
    assert login(new_client(), username=member["code"], password=member["pin"]).status_code == 200


def test_an_email_in_use_is_refused_and_leaves_nothing_behind(new_client: ClientFactory) -> None:
    asyncio.run(_seed("La Taquería", "owner@example.com"))
    before = counts()

    response = register(new_client(), email="OWNER@example.com", business_name="Second Business")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {"type": "about:blank", "title": "Conflict", "status": 409, "detail": "Email already in use"}
    assert "set-cookie" not in response.headers
    assert counts() == before


def test_repeating_the_same_sign_up_signs_in_to_the_account_already_created(new_client: ClientFactory) -> None:
    chosen = str(uuid.uuid4())
    first = new_client()
    assert register(first, id=chosen).status_code == 201

    again = new_client()
    replay = register(again, id=chosen, email="FOUNDER@example.com")

    assert replay.status_code == 201
    assert replay.json() == {"expires_in": 900, "role": "admin"}
    assert again.get("/api/v1/auth/me").json()["tenant"]["id"] == chosen
    assert counts() == (1, 1)


@pytest.mark.parametrize(
    "fields",
    [{"email": "other@example.com"}, {"password": "other-pass-123"}],
)
def test_the_same_id_with_other_credentials_is_refused(new_client: ClientFactory, fields: dict[str, str]) -> None:
    chosen = str(uuid.uuid4())
    assert register(new_client(), id=chosen).status_code == 201

    response = register(new_client(), id=chosen, **fields)

    assert response.status_code == 409
    assert response.json()["detail"] == "That id is already used by something else"
    assert counts() == (1, 1)


def test_an_id_of_another_business_is_refused(new_client: ClientFactory) -> None:
    other = asyncio.run(_seed("La Taquería", "owner@example.com"))

    response = register(new_client(), id=str(other.tenant_id))

    assert response.status_code == 409
    assert response.json()["detail"] == "That id is already used by something else"
    assert counts() == (1, 1)


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"email": "not-an-email"}, "Invalid email"),
        ({"password": "short"}, "Password must have 8 to 128 characters"),
        ({"business_name": "   "}, "Tenant name must have 1 to 120 characters"),
        ({"business_name": "x" * 121}, "Tenant name must have 1 to 120 characters"),
    ],
)
def test_invalid_data_gets_the_domain_message_and_creates_nothing(
    new_client: ClientFactory, fields: dict[str, str], detail: str
) -> None:
    response = register(new_client(), **fields)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert counts() == (0, 0)


@pytest.mark.parametrize(
    "body",
    [
        {"email": EMAIL, "password": PASSWORD},
        {"email": EMAIL, "business_name": "Tacos"},
        {"email": EMAIL, "password": PASSWORD, "business_name": "Tacos", "full_name": "Owner"},
        {"email": EMAIL, "password": PASSWORD, "business_name": "Tacos", "role": "admin"},
        {"email": EMAIL, "password": PASSWORD, "business_name": "Tacos", "tenant_id": str(uuid.uuid4())},
        {"email": EMAIL, "password": PASSWORD, "business_name": "Tacos", "id": "not-a-uuid"},
        {"email": "x" * 300, "password": PASSWORD, "business_name": "Tacos"},
    ],
)
def test_a_malformed_body_is_a_422_problem(new_client: ClientFactory, body: dict[str, str]) -> None:
    response = new_client().post(REGISTER_URL, json=body)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert counts() == (0, 0)


def test_every_sign_up_counts_against_the_client_and_over_the_limit_gets_429(new_client: ClientFactory) -> None:
    client = new_client()
    limit = get_settings().login_max_failures_per_client
    for attempt in range(limit):
        assert register(client, email=f"owner{attempt}@example.com").status_code == 201

    blocked = register(new_client(), email="one-more@example.com")

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many login attempts. Try again later."
    assert int(blocked.headers["Retry-After"]) > 0
    assert counts() == (limit, limit)
    # Signing up is limited on its own: admins still sign in.
    assert login(new_client(), username="owner0@example.com", password=PASSWORD).status_code == 200


def test_sign_up_needs_no_session_and_ignores_the_callers_one(new_client: ClientFactory) -> None:
    seeded = asyncio.run(_seed("La Taquería", "owner@example.com"))
    client = new_client()
    client.cookies.set("access_token", sign(claims_for(uuid.uuid4(), seeded.tenant_id, "table", table_id=str(uuid.uuid4()))))

    response = register(client)

    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    assert counts() == (2, 2)


def test_concurrent_replays_of_one_sign_up_all_sign_in_to_a_single_business(new_client: ClientFactory) -> None:
    from concurrent.futures import ThreadPoolExecutor

    chosen = str(uuid.uuid4())
    clients = [new_client() for _ in range(4)]

    # The email lock makes each replay wait for the first sign-up and then find it (never a 409).
    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        statuses = list(pool.map(lambda client: register(client, id=chosen).status_code, clients))

    assert statuses == [201] * len(clients)
    assert counts() == (1, 1)
