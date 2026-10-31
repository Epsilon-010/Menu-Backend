"""Admin accounts (Slice 17): other admins of the business, password change and the forced first change."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from tests.integration.modules.auth.test_auth_api import PASSWORD, login, me
from tests.integration.modules.staff.test_staff_api import (
    ClientFactory,
    add_member,
    created,
    new_client,  # noqa: F401  (fixture)
    signed_in,
    tenant_a,  # noqa: F401  (fixture)
    tenant_b,  # noqa: F401  (fixture)
)

ADMINS_URL = "/api/v1/admins"
PASSWORD_URL = "/api/v1/auth/password"
NEW_PASSWORD = "brand-new-pass-1"
FORCED_CHANGE = "Change your temporary password first"


def add_admin(admin: TestClient, email: str = "manager@example.com", full_name: str = "Manager", **extra: Any) -> Response:
    return admin.post(ADMINS_URL, json={"full_name": full_name, "email": email, **extra})


def change_password(client: TestClient, current: str, new: str) -> Response:
    return client.post(PASSWORD_URL, json={"current_password": current, "new_password": new})


def detail(response: Response) -> str:
    assert response.headers["content-type"] == "application/problem+json"
    value: str = response.json()["detail"]
    return value


@pytest.fixture
def owner(new_client: ClientFactory, tenant_a: SeedResult) -> TestClient:
    return signed_in(new_client, tenant_a.email)


def ready_admin(new_client: ClientFactory, owner: TestClient, email: str = "manager@example.com") -> TestClient:
    """A second admin who already replaced the temporary password."""
    temporary = created(add_admin(owner, email))["temporary_password"]
    client = signed_in(new_client, email, temporary)
    assert change_password(client, temporary, NEW_PASSWORD).status_code == 200
    return client


# --- S2 create --------------------------------------------------------------------------------


def test_creating_an_admin_returns_a_temporary_password_once(owner: TestClient, tenant_a: SeedResult) -> None:
    body = created(add_admin(owner, " Manager@Example.com ", "  Manager  "))

    temporary = body.pop("temporary_password")
    assert len(temporary) == 12
    assert uuid.UUID(body.pop("id"))
    assert body == {
        "email": "manager@example.com",
        "full_name": "Manager",
        "is_active": True,
        "must_change_password": True,
    }
    listed = owner.get(ADMINS_URL).json()
    assert all("temporary_password" not in admin for admin in listed)


def test_the_new_admin_signs_in_with_the_temporary_password_and_must_change_it(
    new_client: ClientFactory, owner: TestClient
) -> None:
    temporary = created(add_admin(owner))["temporary_password"]
    client = new_client()

    response = login(client, "manager@example.com", temporary)

    assert response.status_code == 200
    assert response.json() == {"expires_in": 900, "role": "admin", "must_change_password": True}
    assert me(client).json()["user"]["must_change_password"] is True


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"full_name": "Manager", "email": "not-an-email"}, "Invalid email"),
        ({"full_name": "   ", "email": "x@example.com"}, "Full name must have 1 to 120 characters"),
    ],
)
def test_creating_an_admin_validates_the_name_and_email(owner: TestClient, body: dict[str, str], message: str) -> None:
    response = owner.post(ADMINS_URL, json=body)

    assert response.status_code == 422
    assert detail(response) == message


def test_an_email_already_used_anywhere_is_a_conflict(owner: TestClient, tenant_b: SeedResult) -> None:
    response = add_admin(owner, "BOSS@example.com")

    assert response.status_code == 409
    assert detail(response) == "Email already in use"


def test_repeating_a_create_with_the_same_id_never_makes_a_second_admin(owner: TestClient) -> None:
    admin_id = str(uuid.uuid4())
    created(add_admin(owner, id=admin_id))

    replay = add_admin(owner, id=admin_id)

    assert replay.status_code == 409
    assert detail(replay) == "This admin was already created"
    assert [admin["id"] for admin in owner.get(ADMINS_URL).json()].count(admin_id) == 1


def test_an_id_used_by_something_else_is_a_conflict_without_details(
    owner: TestClient, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    waiter_id = created(add_member(owner))["id"]

    for clash in (waiter_id, str(tenant_b.user_id)):
        response = add_admin(owner, f"{clash[:8]}@example.com", id=clash)
        assert response.status_code == 409
        assert detail(response) == "That id is already used by something else"


def test_unknown_fields_are_rejected(owner: TestClient) -> None:
    assert add_admin(owner, role="waiter").status_code == 422


# --- S3 list ----------------------------------------------------------------------------------


def test_the_list_has_only_this_tenants_admins_ordered_by_name(
    owner: TestClient, tenant_a: SeedResult, new_client: ClientFactory, tenant_b: SeedResult
) -> None:
    created(add_admin(owner, "zed@example.com", "Zed"))
    created(add_admin(owner, "abe@example.com", "abe"))
    created(add_member(owner))

    listed = owner.get(ADMINS_URL).json()

    assert [admin["full_name"] for admin in listed] == ["abe", "Owner", "Zed"]
    assert listed[1] == {
        "id": str(tenant_a.user_id),
        "email": tenant_a.email,
        "full_name": "Owner",
        "is_active": True,
        "must_change_password": False,
    }
    other = signed_in(new_client, tenant_b.email)
    assert [admin["email"] for admin in other.get(ADMINS_URL).json()] == [tenant_b.email]


# --- S4 manage --------------------------------------------------------------------------------


def test_deactivating_an_admin_ends_their_sessions_and_reactivating_lets_them_back(
    new_client: ClientFactory, owner: TestClient
) -> None:
    manager = ready_admin(new_client, owner)
    manager_id = next(a["id"] for a in owner.get(ADMINS_URL).json() if a["email"] == "manager@example.com")

    response = owner.patch(f"{ADMINS_URL}/{manager_id}", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert manager.get(ADMINS_URL).status_code == 401
    assert login(new_client(), "manager@example.com", NEW_PASSWORD).status_code == 401

    assert owner.patch(f"{ADMINS_URL}/{manager_id}", json={"is_active": True}).json()["is_active"] is True
    assert login(new_client(), "manager@example.com", NEW_PASSWORD).status_code == 200


def test_an_admin_can_be_renamed(owner: TestClient) -> None:
    admin_id = created(add_admin(owner))["id"]

    response = owner.patch(f"{ADMINS_URL}/{admin_id}", json={"full_name": " Night manager "})

    assert response.status_code == 200
    assert response.json()["full_name"] == "Night manager"


def test_nobody_can_deactivate_their_own_account(owner: TestClient, tenant_a: SeedResult) -> None:
    response = owner.patch(f"{ADMINS_URL}/{tenant_a.user_id}", json={"is_active": False})

    assert response.status_code == 409
    assert detail(response) == "You cannot deactivate your own account"
    assert owner.get(ADMINS_URL).status_code == 200


def test_a_deactivated_admin_with_a_live_token_cannot_deactivate_anyone(
    new_client: ClientFactory, owner: TestClient, tenant_a: SeedResult
) -> None:
    manager = ready_admin(new_client, owner)
    manager_id = next(a["id"] for a in owner.get(ADMINS_URL).json() if a["email"] == "manager@example.com")
    # Simulates the race: the manager's request runs after the owner's committed, with a token still valid
    # (as if Redis lost the revocation).
    manager_cookie = manager.cookies.get("access_token")
    assert owner.patch(f"{ADMINS_URL}/{manager_id}", json={"is_active": False}).status_code == 200

    from app.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as raw:
        raw.app.state.access_revocations = _NoRevocations()  # type: ignore[attr-defined]
        response = raw.patch(
            f"{ADMINS_URL}/{tenant_a.user_id}",
            json={"is_active": False},
            headers={"Cookie": f"access_token={manager_cookie}"},
        )

    assert response.status_code == 403
    assert detail(response) == "Not allowed"
    assert owner.get(ADMINS_URL).status_code == 200


class _NoRevocations:
    async def require_version(self, subject_id: uuid.UUID, session_version: int) -> None:
        return None

    async def required_version(self, subject_id: uuid.UUID) -> int | None:
        return None


def test_waiters_other_tenants_and_unknown_ids_are_not_admins(
    new_client: ClientFactory, owner: TestClient, tenant_b: SeedResult
) -> None:
    waiter_id = created(add_member(owner))["id"]

    for target in (waiter_id, str(tenant_b.user_id), str(uuid.uuid4())):
        response = owner.patch(f"{ADMINS_URL}/{target}", json={"is_active": False})
        assert response.status_code == 404
        assert detail(response) == "Admin not found"
    assert login(new_client(), tenant_b.email).status_code == 200


# --- S5 change password -----------------------------------------------------------------------


def test_changing_the_password_signs_out_other_devices_and_keeps_this_one(
    new_client: ClientFactory, owner: TestClient, tenant_a: SeedResult
) -> None:
    other_device = signed_in(new_client, tenant_a.email)

    response = change_password(owner, PASSWORD, NEW_PASSWORD)

    assert response.status_code == 200
    assert response.json() == {"expires_in": 900, "role": "admin", "must_change_password": False}
    assert owner.get(ADMINS_URL).status_code == 200
    assert other_device.get(ADMINS_URL).status_code == 401
    assert login(new_client(), tenant_a.email, PASSWORD).status_code == 401
    assert login(new_client(), tenant_a.email, NEW_PASSWORD).status_code == 200


def test_a_wrong_current_password_is_rejected_and_counted(owner: TestClient) -> None:
    for _ in range(get_settings().login_max_failures_per_client):
        response = change_password(owner, "not-my-password", NEW_PASSWORD)
        assert response.status_code == 400
        assert detail(response) == "The current password is incorrect"

    blocked = change_password(owner, PASSWORD, NEW_PASSWORD)

    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


@pytest.mark.parametrize(
    ("new", "message"),
    [
        ("short", "Password must have 8 to 128 characters"),
        ("x" * 129, "Password must have 8 to 128 characters"),
        (PASSWORD, "The new password must be different from the current one"),
    ],
)
def test_the_new_password_is_validated(owner: TestClient, tenant_a: SeedResult, new: str, message: str) -> None:
    response = change_password(owner, PASSWORD, new)

    assert response.status_code == 422
    assert detail(response) == message


def test_only_admins_change_passwords(new_client: ClientFactory, owner: TestClient) -> None:
    waiter = created(add_member(owner))
    client = signed_in(new_client, waiter["code"], waiter["pin"])

    response = change_password(client, waiter["pin"], NEW_PASSWORD)

    assert response.status_code == 403


def test_the_password_body_rejects_unknown_fields(owner: TestClient) -> None:
    response = owner.post(PASSWORD_URL, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD, "x": 1})

    assert response.status_code == 422


# --- S6 forced change -------------------------------------------------------------------------


def test_an_admin_with_a_temporary_password_can_do_nothing_else_until_changing_it(
    new_client: ClientFactory, owner: TestClient
) -> None:
    temporary = created(add_admin(owner))["temporary_password"]
    client = signed_in(new_client, "manager@example.com", temporary)

    for response in (client.get(ADMINS_URL), client.get("/api/v1/staff"), client.get("/api/v1/tables")):
        assert response.status_code == 403
        assert detail(response) == FORCED_CHANGE
    assert me(client).status_code == 200
    assert client.post("/api/v1/auth/refresh").json()["must_change_password"] is True
    assert client.get(ADMINS_URL).status_code == 403

    changed = change_password(client, temporary, NEW_PASSWORD)

    assert changed.json()["must_change_password"] is False
    assert client.get(ADMINS_URL).status_code == 200
    assert me(client).json()["user"]["must_change_password"] is False
    listed = owner.get(ADMINS_URL).json()
    assert next(a for a in listed if a["email"] == "manager@example.com")["must_change_password"] is False


# --- S8 roles -----------------------------------------------------------------------------------


def test_non_admin_roles_get_403_on_every_admin_endpoint(new_client: ClientFactory, owner: TestClient) -> None:
    for role in ("waiter", "kitchen"):
        member = created(add_member(owner, role=role))
        client = signed_in(new_client, member["code"], member["pin"])
        responses = [
            client.get(ADMINS_URL),
            add_admin(client, f"{role}@example.com"),
            client.patch(f"{ADMINS_URL}/{uuid.uuid4()}", json={"is_active": False}),
        ]
        assert [response.status_code for response in responses] == [403, 403, 403]


def test_admin_endpoints_require_a_session(new_client: ClientFactory) -> None:
    client = new_client()

    assert client.get(ADMINS_URL).status_code == 401
    assert change_password(client, PASSWORD, NEW_PASSWORD).status_code == 401


def test_only_a_temporary_password_session_carries_the_change_claim(
    new_client: ClientFactory, owner: TestClient
) -> None:
    from jose import jwt

    secret = get_settings().jwt_secret.get_secret_value()
    temporary = created(add_admin(owner))["temporary_password"]
    client = new_client()
    forced = login(client, "manager@example.com", temporary)

    assert jwt.decode(forced.cookies["access_token"], secret, algorithms=["HS256"])["pwc"] is True
    changed = change_password(client, temporary, NEW_PASSWORD)
    assert "pwc" not in jwt.decode(changed.cookies["access_token"], secret, algorithms=["HS256"])
