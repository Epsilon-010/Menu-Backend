import asyncio
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import update

from app.modules.staff.domain.user import STAFF_CODE_ALPHABET
from app.modules.staff.infrastructure.models import UserModel
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from app.shared.infrastructure.security import Argon2PasswordHasher
from tests.integration.modules.auth.test_auth_api import (
    GENERIC_LOGIN_ERROR,
    PASSWORD,
    _seed,
    claims_for,
    login,
    me,
    refresh_with,
    sign,
    unrevoke_refresh_tokens,
)

STAFF_URL = "/api/v1/staff"
# Password of the legacy-style accounts `create_member` makes for the other modules' tests.
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


def add_member(admin: TestClient, full_name: str = "Juan Pérez", role: str = "waiter", **extra: Any) -> Response:
    """Creates a waiter or cook the way the admin panel does: only a name and a role."""
    return admin.post(STAFF_URL, json={"full_name": full_name, "role": role, **extra})


def created(response: Response) -> dict[str, Any]:
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def member_id(response: Response) -> str:
    return str(created(response)["id"])


def _make_legacy(user_id: str, username: str, password: str) -> None:
    """Turns a member into an account from before codes existed (chosen username + password, S8)."""

    async def run() -> None:
        engine = create_engine(get_settings().database_url)
        try:
            async with create_session_factory(engine)() as session:
                await session.execute(
                    update(UserModel)
                    .where(UserModel.id == uuid.UUID(user_id))
                    .values(username=username, password_hash=await Argon2PasswordHasher().hash(password))
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def create_member(admin: TestClient, username: str, role: str = "waiter", **extra: Any) -> Response:
    """For the other modules' tests, which sign members in with a known login: creates the member through
    the API and, when it is created, makes it a legacy account `username` / STAFF_PASSWORD (still valid)."""
    response = add_member(admin, "Juan Pérez", role, **extra)
    if response.status_code == 201:
        _make_legacy(str(response.json()["id"]), username, STAFF_PASSWORD)
    return response


# --- S4: the admin types only a name; the backend generates the code and the PIN --------------


def test_admin_creates_a_waiter_and_a_cook_with_only_a_name_and_each_signs_in_with_code_and_pin(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")

    waiter = created(add_member(admin, " Juan Pérez ", "waiter"))
    cook = created(add_member(admin, "Pedro López", "kitchen"))

    assert waiter == {
        "id": waiter["id"],
        "code": waiter["code"],
        "full_name": "Juan Pérez",
        "role": "waiter",
        "is_active": True,
        "pin": waiter["pin"],
    }
    for member in (waiter, cook):
        assert len(member["code"]) == 6 and set(member["code"]) <= set(STAFF_CODE_ALPHABET)
        assert len(member["pin"]) == 6 and member["pin"].isdigit()
    assert waiter["code"] != cook["code"]
    # The PIN is shown once: the list never carries it.
    listed = admin.get(STAFF_URL)
    assert listed.status_code == 200
    assert listed.json() == [{k: v for k, v in m.items() if k != "pin"} for m in (waiter, cook)]

    for member in (waiter, cook):
        client = new_client()
        session = login(client, username=member["code"], password=member["pin"])
        assert session.status_code == 200
        assert session.json()["role"] == member["role"]
        account = client.get("/api/v1/auth/me").json()
        assert account["user"]["id"] == member["id"]
        assert account["user"]["email"] is None
        assert account["tenant"] == {"id": str(tenant_a.tenant_id), "name": "La Taquería"}


def test_staff_sessions_last_one_shift(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    member = created(add_member(signed_in(new_client, "owner@example.com")))

    response = login(new_client(), username=member["code"], password=member["pin"])

    refresh_cookie = next(h for h in response.headers.get_list("set-cookie") if h.startswith("refresh_token="))
    assert f"Max-Age={12 * 3600}" in refresh_cookie


# --- S6: code in any case + PIN, through the existing login, with the same generic error -----


def test_the_code_works_in_any_case_and_a_wrong_pin_gets_the_generic_error(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    member = created(add_member(signed_in(new_client, "owner@example.com")))
    wrong_pin = "000000" if member["pin"] != "000000" else "111111"

    assert login(new_client(), username=member["code"].lower(), password=member["pin"]).status_code == 200
    assert login(new_client(), username=f" {member['code']} ", password=member["pin"]).status_code == 200
    wrong = login(new_client(), username=member["code"], password=wrong_pin)
    assert wrong.status_code == 401
    assert wrong.json() == GENERIC_LOGIN_ERROR
    # The name is never a login.
    assert login(new_client(), username="Juan Pérez", password=member["pin"]).json() == GENERIC_LOGIN_ERROR


# --- S5: names repeat freely; the code tells members apart -----------------------------------


def test_two_members_with_the_same_name_in_one_tenant_and_in_two_tenants_never_share_a_login(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin_a = signed_in(new_client, "owner@example.com")
    admin_b = signed_in(new_client, "boss@example.com")
    members = [
        created(add_member(admin_a, "Juan Pérez")),
        created(add_member(admin_a, "Juan Pérez")),
        created(add_member(admin_b, "Juan Pérez")),
    ]

    assert len({member["code"] for member in members}) == 3
    for member in members:
        client = signed_in(new_client, member["code"], member["pin"])
        assert client.get("/api/v1/auth/me").json()["user"]["id"] == member["id"]
        for other in members:
            if other["id"] != member["id"] and other["pin"] != member["pin"]:
                assert login(new_client(), username=member["code"], password=other["pin"]).status_code == 401


# --- S9: only the admin manages staff ---------------------------------------------------------


@pytest.mark.parametrize("role", ["waiter", "kitchen", "table", "guest"])
def test_non_admin_roles_get_403_on_every_staff_endpoint(
    new_client: ClientFactory, tenant_a: SeedResult, role: str
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))
    if role in ("table", "guest"):
        caller = new_client()
        extra: dict[str, str] = {"table_id": str(uuid.uuid4())}
        if role == "guest":
            extra["bill_id"] = str(uuid.uuid4())
        caller.cookies.set("access_token", sign(claims_for(uuid.uuid4(), tenant_a.tenant_id, role, **extra)))
    else:
        member = created(add_member(admin, "Caller", role))
        caller = signed_in(new_client, member["code"], member["pin"])

    responses = [
        caller.get(STAFF_URL),
        add_member(caller, "Intruder"),
        caller.patch(f"{STAFF_URL}/{target['id']}", json={"is_active": False}),
        caller.post(f"{STAFF_URL}/{target['id']}/pin"),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert "Intruder" not in [member["full_name"] for member in admin.get(STAFF_URL).json()]
    assert login(new_client(), username=target["code"], password=target["pin"]).status_code == 200


def test_anonymous_callers_get_401(new_client: ClientFactory) -> None:
    assert new_client().get(STAFF_URL).status_code == 401


def test_the_old_password_endpoint_is_gone(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))

    response = admin.put(f"{STAFF_URL}/{target['id']}/password", json={"password": "new-shift-456"})

    assert response.status_code in (404, 405)
    assert login(new_client(), username=target["code"], password=target["pin"]).status_code == 200


# --- Deactivation, role change -----------------------------------------------------------------


def test_deactivating_a_waiter_ends_their_active_session_at_once(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))
    waiter = signed_in(new_client, target["code"], target["pin"])
    assert waiter.get("/api/v1/auth/me").status_code == 200

    response = admin.patch(f"{STAFF_URL}/{target['id']}", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["code"] == target["code"]
    assert "pin" not in response.json()
    # The still unexpired access cookie is rejected, and so is the refresh cookie.
    assert waiter.get("/api/v1/auth/me").status_code == 401
    assert waiter.post("/api/v1/auth/refresh").status_code == 401
    assert login(new_client(), username=target["code"], password=target["pin"]).json() == GENERIC_LOGIN_ERROR


def test_a_reactivated_waiter_can_sign_in_again(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))
    admin.patch(f"{STAFF_URL}/{target['id']}", json={"is_active": False})

    admin.patch(f"{STAFF_URL}/{target['id']}", json={"is_active": True})

    waiter = signed_in(new_client, target["code"], target["pin"])
    assert waiter.get("/api/v1/auth/me").status_code == 200


def test_changing_the_role_ends_the_session_and_renaming_does_not(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))
    waiter = signed_in(new_client, target["code"], target["pin"])

    renamed = admin.patch(f"{STAFF_URL}/{target['id']}", json={"full_name": "Juan P."})
    assert renamed.json()["full_name"] == "Juan P."
    assert waiter.get("/api/v1/auth/me").status_code == 200

    moved = admin.patch(f"{STAFF_URL}/{target['id']}", json={"role": "kitchen"})
    assert moved.json()["role"] == "kitchen"
    assert waiter.get("/api/v1/auth/me").status_code == 401
    cook = signed_in(new_client, target["code"], target["pin"])
    assert cook.get("/api/v1/auth/me").json()["user"]["role"] == "kitchen"


# --- S7: a new PIN keeps the code and ends every session -------------------------------------


def test_regenerating_the_pin_keeps_the_code_ends_the_sessions_and_only_the_new_pin_works(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))
    waiter = signed_in(new_client, target["code"], target["pin"])

    response = admin.post(f"{STAFF_URL}/{target['id']}/pin")

    assert response.status_code == 200
    renewed = response.json()
    assert {k: v for k, v in renewed.items() if k != "pin"} == {k: v for k, v in target.items() if k != "pin"}
    assert len(renewed["pin"]) == 6 and renewed["pin"].isdigit()
    assert waiter.get("/api/v1/auth/me").status_code == 401
    assert waiter.post("/api/v1/auth/refresh").status_code == 401
    if renewed["pin"] != target["pin"]:
        assert login(new_client(), username=target["code"], password=target["pin"]).status_code == 401
    assert login(new_client(), username=target["code"], password=renewed["pin"]).status_code == 200


def test_a_staff_session_that_escaped_the_new_pin_is_rejected(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))
    refresh_token = signed_in(new_client, target["code"], target["pin"]).cookies.get("refresh_token")

    assert admin.post(f"{STAFF_URL}/{target['id']}/pin").status_code == 200
    unrevoke_refresh_tokens(user_id=uuid.UUID(target["id"]))
    signed_later = {"iat": datetime.now(UTC) + timedelta(seconds=2), "sv": 1}
    stale = sign({**claims_for(uuid.UUID(target["id"]), tenant_a.tenant_id, "waiter"), **signed_later})

    assert me(new_client(), stale).status_code == 401
    assert refresh_with(new_client(), refresh_token).status_code == 401


# --- S8: accounts from before codes keep their login until a new PIN ---------------------------


def test_a_legacy_member_keeps_their_username_and_password_until_the_admin_generates_a_pin(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = member_id(create_member(admin, "demo.mesero"))

    assert admin.get(STAFF_URL).json()[0]["code"] == "DEMO.MESERO"
    assert login(new_client(), username="demo.mesero", password=STAFF_PASSWORD).status_code == 200

    renewed = admin.post(f"{STAFF_URL}/{target}/pin").json()

    assert renewed["code"] == "DEMO.MESERO"
    assert login(new_client(), username="demo.mesero", password=STAFF_PASSWORD).status_code == 401
    assert login(new_client(), username="DEMO.MESERO", password=renewed["pin"]).status_code == 200


# --- Validation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": "Juan", "role": "admin"},
        {"full_name": "Juan", "role": "table"},
        {"full_name": "", "role": "waiter"},
        {"full_name": "j" * 121, "role": "waiter"},
        {"role": "waiter"},
        {"full_name": "Juan"},
        # The old contract: credentials are never chosen by the admin any more.
        {"full_name": "Juan", "role": "waiter", "username": "juan"},
        {"full_name": "Juan", "role": "waiter", "password": STAFF_PASSWORD},
        {"full_name": "Juan", "role": "waiter", "pin": "123456"},
    ],
)
def test_invalid_staff_data_is_rejected(new_client: ClientFactory, tenant_a: SeedResult, body: dict[str, str]) -> None:
    admin = signed_in(new_client, "owner@example.com")

    response = admin.post(STAFF_URL, json=body)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert admin.get(STAFF_URL).json() == []


def test_a_blank_name_gets_the_domain_message(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    response = add_member(signed_in(new_client, "owner@example.com"), "   ")

    assert response.status_code == 422
    assert response.json()["detail"] == "Full name must have 1 to 120 characters"


@pytest.mark.parametrize("body", [{"role": "admin"}, {"full_name": " "}, {"is_active": "maybe"}, {"code": "AAAAAA"}])
def test_invalid_updates_are_rejected_without_changes(
    new_client: ClientFactory, tenant_a: SeedResult, body: dict[str, str]
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin))

    assert admin.patch(f"{STAFF_URL}/{target['id']}", json=body).status_code == 422
    [member] = admin.get(STAFF_URL).json()
    assert (member["role"], member["code"], member["full_name"]) == ("waiter", target["code"], "Juan Pérez")


# --- Tenant isolation -----------------------------------------------------------------------


def test_an_admin_never_sees_nor_changes_another_tenants_staff(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin_a = signed_in(new_client, "owner@example.com")
    target = created(add_member(admin_a))
    waiter = signed_in(new_client, target["code"], target["pin"])
    admin_b = signed_in(new_client, "boss@example.com")

    assert admin_b.get(STAFF_URL).json() == []
    assert admin_b.patch(f"{STAFF_URL}/{target['id']}", json={"is_active": False}).status_code == 404
    assert admin_b.post(f"{STAFF_URL}/{target['id']}/pin").status_code == 404

    assert waiter.get("/api/v1/auth/me").status_code == 200
    assert admin_a.get(STAFF_URL).json()[0]["is_active"] is True
    assert login(new_client(), username=target["code"], password=target["pin"]).status_code == 200


def test_admins_are_not_managed_from_the_staff_endpoints(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = signed_in(new_client, "owner@example.com")

    assert admin.patch(f"{STAFF_URL}/{tenant_a.user_id}", json={"is_active": False}).status_code == 404
    assert admin.post(f"{STAFF_URL}/{tenant_a.user_id}/pin").status_code == 404
    assert admin.get("/api/v1/auth/me").status_code == 200
    assert login(new_client(), username="owner@example.com", password=PASSWORD).status_code == 200


# --- Idempotency -----------------------------------------------------------------------------


def test_repeating_a_staff_create_with_its_id_never_makes_a_second_member(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = signed_in(new_client, "owner@example.com")
    chosen = str(uuid.uuid4())

    first = created(add_member(admin, id=chosen))
    replay = add_member(admin, id=chosen)
    other_data = add_member(admin, "Other Name", "kitchen", id=chosen)
    other_tenant = add_member(signed_in(new_client, "boss@example.com"), id=chosen)
    admin_id = add_member(admin, id=str(tenant_a.user_id))

    already = "This staff member was already created; generate a new PIN to see the credentials"
    assert first["id"] == chosen
    assert (replay.status_code, replay.json()["detail"]) == (409, already)
    assert (other_data.status_code, other_data.json()["detail"]) == (409, already)
    for clash in (other_tenant, admin_id):
        assert clash.status_code == 409
        assert clash.json()["detail"] == "That id is already used by something else"
    assert [m["id"] for m in admin.get(STAFF_URL).json()] == [chosen]
    # The PIN is still the first one.
    assert login(new_client(), username=first["code"], password=first["pin"]).status_code == 200
