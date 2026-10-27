import asyncio
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import PASSWORD, _seed, claims_for, login, sign

STAFF_URL = "/api/v1/staff"
STAFF_PASSWORD = "shift-pass-123"

ClientFactory = Callable[[], TestClient]


@pytest.fixture
def tenant_a() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


@pytest.fixture
def tenant_b() -> SeedResult:
    return asyncio.run(_seed("Burger Place", "boss@example.com"))


@pytest.fixture
def new_client() -> Iterator[ClientFactory]:
    """Each actor (admin, waiter, cook...) needs its own cookie jar."""
    from app.main import create_app

    with ExitStack() as stack:
        yield lambda: stack.enter_context(TestClient(create_app(), base_url="https://testserver"))


def signed_in(new_client: ClientFactory, username: str, password: str = PASSWORD) -> TestClient:
    client = new_client()
    assert login(client, username=username, password=password).status_code == 200
    return client


def create_member(admin: TestClient, username: str, role: str = "waiter", **extra: Any) -> Response:
    body = {"username": username, "full_name": "Juan Pérez", "role": role, "password": STAFF_PASSWORD, **extra}
    return admin.post(STAFF_URL, json=body)


def member_id(response: Response) -> str:
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# --- Done when: "Creo un mesero y un cocinero, entro con cada uno y llego a su vista." -------


def test_admin_creates_a_waiter_and_a_cook_and_each_signs_in_with_their_role(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")

    waiter = create_member(admin, " Juan.Taco ", "waiter")
    cook = create_member(admin, "maria.taco", "kitchen", full_name="María López")

    assert waiter.status_code == 201
    assert waiter.json() == {
        "id": waiter.json()["id"],
        "username": "juan.taco",
        "full_name": "Juan Pérez",
        "role": "waiter",
        "is_active": True,
    }
    assert cook.json()["role"] == "kitchen"
    listed = admin.get(STAFF_URL)
    assert listed.status_code == 200
    assert [member["username"] for member in listed.json()] == ["juan.taco", "maria.taco"]

    for username, role in (("juan.taco", "waiter"), ("maria.taco", "kitchen")):
        client = new_client()
        session = login(client, username=username, password=STAFF_PASSWORD)
        assert session.status_code == 200
        assert session.json()["role"] == role
        account = client.get("/api/v1/auth/me").json()
        assert account["user"]["username"] == username
        assert account["user"]["email"] is None
        assert account["user"]["role"] == role
        assert account["tenant"] == {"id": str(tenant_a.tenant_id), "name": "La Taquería"}


def test_staff_sessions_last_one_shift(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = signed_in(new_client, "owner@example.com")
    member_id(create_member(admin, "juan.taco"))

    response = login(new_client(), username="juan.taco", password=STAFF_PASSWORD)

    refresh_cookie = next(h for h in response.headers.get_list("set-cookie") if h.startswith("refresh_token="))
    assert f"Max-Age={12 * 3600}" in refresh_cookie


# --- Done when: "Un mesero o cocinero recibe 403 en endpoints de admin (tests por rol)." -----


@pytest.mark.parametrize("role", ["waiter", "kitchen", "table"])
def test_non_admin_roles_get_403_on_every_staff_endpoint(
    new_client: ClientFactory, tenant_a: SeedResult, role: str
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin, "juan.taco"))
    if role == "table":
        caller = new_client()
        extra = {"table_id": str(uuid.uuid4())}
        caller.cookies.set("access_token", sign(claims_for(uuid.uuid4(), tenant_a.tenant_id, "table", **extra)))
    else:
        member_id(create_member(admin, "caller", role))
        caller = signed_in(new_client, "caller", STAFF_PASSWORD)

    responses = [
        caller.get(STAFF_URL),
        create_member(caller, "intruder"),
        caller.patch(f"{STAFF_URL}/{target}", json={"is_active": False}),
        caller.put(f"{STAFF_URL}/{target}/password", json={"password": "hijacked-123"}),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert [member["username"] for member in admin.get(STAFF_URL).json()].count("intruder") == 0
    assert login(new_client(), username="juan.taco", password=STAFF_PASSWORD).status_code == 200


def test_anonymous_callers_get_401(new_client: ClientFactory) -> None:
    assert new_client().get(STAFF_URL).status_code == 401


# --- Done when: "Desactivar al mesero cierra su sesión activa." -------------------------------


def test_deactivating_a_waiter_ends_their_active_session_at_once(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin, "juan.taco"))
    waiter = signed_in(new_client, "juan.taco", STAFF_PASSWORD)
    assert waiter.get("/api/v1/auth/me").status_code == 200

    response = admin.patch(f"{STAFF_URL}/{target}", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    # The still unexpired access cookie is rejected, and so is the refresh cookie.
    assert waiter.get("/api/v1/auth/me").status_code == 401
    assert waiter.post("/api/v1/auth/refresh").status_code == 401
    assert login(new_client(), username="juan.taco", password=STAFF_PASSWORD).status_code == 401


def test_a_reactivated_waiter_can_sign_in_again(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin, "juan.taco"))
    admin.patch(f"{STAFF_URL}/{target}", json={"is_active": False})

    admin.patch(f"{STAFF_URL}/{target}", json={"is_active": True})

    waiter = signed_in(new_client, "juan.taco", STAFF_PASSWORD)
    assert waiter.get("/api/v1/auth/me").status_code == 200


def test_changing_the_role_ends_the_session_and_renaming_does_not(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin, "juan.taco"))
    waiter = signed_in(new_client, "juan.taco", STAFF_PASSWORD)

    renamed = admin.patch(f"{STAFF_URL}/{target}", json={"full_name": "Juan P."})
    assert renamed.json()["full_name"] == "Juan P."
    assert waiter.get("/api/v1/auth/me").status_code == 200

    moved = admin.patch(f"{STAFF_URL}/{target}", json={"role": "kitchen"})
    assert moved.json()["role"] == "kitchen"
    assert waiter.get("/api/v1/auth/me").status_code == 401
    cook = signed_in(new_client, "juan.taco", STAFF_PASSWORD)
    assert cook.get("/api/v1/auth/me").json()["user"]["role"] == "kitchen"


def test_resetting_a_password_ends_the_sessions_and_only_the_new_one_works(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin, "juan.taco"))
    waiter = signed_in(new_client, "juan.taco", STAFF_PASSWORD)

    response = admin.put(f"{STAFF_URL}/{target}/password", json={"password": "new-shift-456"})

    assert response.status_code == 204
    assert waiter.get("/api/v1/auth/me").status_code == 401
    assert login(new_client(), username="juan.taco", password=STAFF_PASSWORD).status_code == 401
    assert login(new_client(), username="juan.taco", password="new-shift-456").status_code == 200


# --- Validation ------------------------------------------------------------------------------


def test_a_username_taken_in_another_tenant_is_not_available(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    member_id(create_member(signed_in(new_client, "owner@example.com"), "juan"))

    response = create_member(signed_in(new_client, "boss@example.com"), "JUAN")

    assert response.status_code == 409
    assert response.json() == {"type": "about:blank", "title": "Conflict", "status": 409, "detail": "Username not available"}


@pytest.mark.parametrize(
    "body",
    [
        {"username": "ju", "full_name": "Juan", "role": "waiter", "password": STAFF_PASSWORD},
        {"username": "juan@taco", "full_name": "Juan", "role": "waiter", "password": STAFF_PASSWORD},
        {"username": "juan", "full_name": "Juan", "role": "admin", "password": STAFF_PASSWORD},
        {"username": "juan", "full_name": "Juan", "role": "waiter", "password": "short"},
        {"username": "juan", "full_name": "", "role": "waiter", "password": STAFF_PASSWORD},
        {"username": "juan", "role": "waiter", "password": STAFF_PASSWORD},
    ],
)
def test_invalid_staff_data_is_rejected(new_client: ClientFactory, tenant_a: SeedResult, body: dict[str, str]) -> None:
    admin = signed_in(new_client, "owner@example.com")

    assert admin.post(STAFF_URL, json=body).status_code == 422
    assert admin.get(STAFF_URL).json() == []


@pytest.mark.parametrize("body", [{"role": "admin"}, {"full_name": " "}, {"is_active": "maybe"}])
def test_invalid_updates_are_rejected_without_changes(
    new_client: ClientFactory, tenant_a: SeedResult, body: dict[str, str]
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin, "juan.taco"))

    assert admin.patch(f"{STAFF_URL}/{target}", json=body).status_code == 422
    assert admin.get(STAFF_URL).json()[0]["role"] == "waiter"


# --- Tenant isolation -----------------------------------------------------------------------


def test_an_admin_never_sees_nor_changes_another_tenants_staff(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin_a = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin_a, "juan.taco"))
    waiter = signed_in(new_client, "juan.taco", STAFF_PASSWORD)
    admin_b = signed_in(new_client, "boss@example.com")

    assert admin_b.get(STAFF_URL).json() == []
    assert admin_b.patch(f"{STAFF_URL}/{target}", json={"is_active": False}).status_code == 404
    assert admin_b.put(f"{STAFF_URL}/{target}/password", json={"password": "hijacked-123"}).status_code == 404

    assert waiter.get("/api/v1/auth/me").status_code == 200
    assert admin_a.get(STAFF_URL).json()[0]["is_active"] is True


def test_admins_are_not_managed_from_the_staff_endpoints(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = signed_in(new_client, "owner@example.com")

    response = admin.patch(f"{STAFF_URL}/{tenant_a.user_id}", json={"is_active": False})

    assert response.status_code == 404
    assert admin.get("/api/v1/auth/me").status_code == 200
