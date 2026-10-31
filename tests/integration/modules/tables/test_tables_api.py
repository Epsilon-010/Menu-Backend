import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from collections.abc import Callable, Iterator
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import (
    _seed,
    claims_for,
    login,
    me,
    refresh_with,
    set_cookies,
    sign,
    unrevoke_refresh_tokens,
)
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, STAFF_URL, create_member, member_id

TABLES_URL = "/api/v1/tables"
TABLE_LOGIN_URL = "/api/v1/auth/table-login"
GENERIC_TABLE_LOGIN_ERROR = {
    "type": "about:blank",
    "title": "Unauthorized",
    "status": 401,
    "detail": "Invalid table code or PIN",
}
CODE_PATTERN = re.compile(r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{6}$")

ClientFactory = Callable[[], TestClient]


@pytest.fixture
def tenant_a() -> SeedResult:
    return asyncio.run(_seed("La Taquería", "owner@example.com"))


@pytest.fixture
def tenant_b() -> SeedResult:
    return asyncio.run(_seed("Burger Place", "boss@example.com"))


@pytest.fixture
def new_client() -> Iterator[ClientFactory]:
    """Each actor (admin, tablet, waiter...) needs its own cookie jar."""
    from app.main import create_app

    with ExitStack() as stack:
        yield lambda: stack.enter_context(TestClient(create_app(), base_url="https://testserver"))


def admin_of(new_client: ClientFactory, email: str = "owner@example.com") -> TestClient:
    client = new_client()
    assert login(client, username=email).status_code == 200
    return client


def create_table(admin: TestClient, name: str = "Mesa 4") -> Response:
    return admin.post(TABLES_URL, json={"name": name})


def created(response: Response) -> dict[str, str]:
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    return body


def table_login(client: TestClient, code: str, pin: str) -> Response:
    return client.post(TABLE_LOGIN_URL, json={"code": code, "pin": pin})


def tablet_of(new_client: ClientFactory, table: dict[str, str]) -> TestClient:
    client = new_client()
    assert table_login(client, table["code"], table["pin"]).status_code == 200
    return client


# --- Done when: "Creo la "Mesa 4", entro con sus credenciales desde otra pestaña y veo `/menu` como Mesa 4."


def test_admin_creates_a_table_and_its_tablet_signs_in_as_that_table(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)

    table = created(create_table(admin, " Mesa 4 "))

    assert table == {
        "id": table["id"],
        "name": "Mesa 4",
        "code": table["code"],
        "is_active": True,
        "qr_token": table["qr_token"],
        "pin": table["pin"],
    }
    assert CODE_PATTERN.match(table["code"])
    assert len(table["qr_token"]) >= 32
    assert re.fullmatch(r"\d{6}", table["pin"])
    # The PIN is shown only once: the list never returns it.
    assert admin.get(TABLES_URL).json() == [
        {"id": table["id"], "name": "Mesa 4", "code": table["code"], "is_active": True, "qr_token": table["qr_token"]}
    ]

    tablet = new_client()
    session = table_login(tablet, table["code"].lower(), table["pin"])
    assert session.status_code == 200
    assert session.json() == {"expires_in": 900, "role": "table", "must_change_password": False}
    assert f"Max-Age={30 * 24 * 3600}" in set_cookies(session)["refresh_token"]

    me = tablet.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json() == {
        "user": None,
        "table": {"id": table["id"], "name": "Mesa 4"},
        "guest": None,
        "tenant": {"id": str(tenant_a.tenant_id), "name": "La Taquería"},
    }
    # The 30-day session renews itself as the same table.
    assert tablet.post("/api/v1/auth/refresh").json() == {"expires_in": 900, "role": "table", "must_change_password": False}
    assert tablet.get("/api/v1/auth/me").json()["table"]["name"] == "Mesa 4"


@pytest.mark.parametrize(("code", "pin"), [("unknown", "123456"), ("real", "000000")])
def test_table_login_fails_generically(
    new_client: ClientFactory, tenant_a: SeedResult, code: str, pin: str
) -> None:
    table = created(create_table(admin_of(new_client)))
    if pin == table["pin"]:
        pin = "999999"

    response = table_login(new_client(), table["code"] if code == "real" else "ZZZZZZ", pin)

    assert response.status_code == 401
    assert response.json() == GENERIC_TABLE_LOGIN_ERROR
    assert "set-cookie" not in response.headers


def test_admin_renames_a_table_without_signing_its_tablet_out(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)

    response = admin.patch(f"{TABLES_URL}/{table['id']}", json={"name": "Terraza 1"})

    assert response.status_code == 200
    assert response.json() == {"id": table["id"], "name": "Terraza 1", "code": table["code"], "is_active": True, "qr_token": table["qr_token"]}
    assert tablet.get("/api/v1/auth/me").json()["table"]["name"] == "Terraza 1"


def test_table_names_are_unique_per_tenant_and_validated(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    created(create_table(admin, "Mesa 4"))

    assert create_table(admin, "MESA 4").status_code == 409
    assert create_table(admin, "   ").status_code == 422
    assert create_table(admin, "x" * 61).status_code == 422
    # Another tenant may use the same name.
    assert create_table(admin_of(new_client, "boss@example.com"), "Mesa 4").status_code == 201


# --- Done when: "Un token `table` recibe 403 en cualquier endpoint de admin, mesero o cocina." ---


def test_a_table_token_gets_403_on_every_admin_endpoint(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    waiter = member_id(create_member(admin, "juan.taco"))
    tablet = tablet_of(new_client, table)

    responses = [
        tablet.get(TABLES_URL),
        create_table(tablet, "Intrusa"),
        tablet.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False}),
        tablet.post(f"{TABLES_URL}/{table['id']}/pin"),
        tablet.get(STAFF_URL),
        create_member(tablet, "intruder"),
        tablet.patch(f"{STAFF_URL}/{waiter}", json={"is_active": False}),
        tablet.post(f"{STAFF_URL}/{waiter}/pin"),
    ]

    assert [response.status_code for response in responses] == [403] * 8
    assert [t["name"] for t in admin.get(TABLES_URL).json()] == ["Mesa 4"]
    assert tablet.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("role", ["waiter", "kitchen"])
def test_waiters_and_cooks_get_403_on_table_management(
    new_client: ClientFactory, tenant_a: SeedResult, role: str
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    member_id(create_member(admin, "staff.member", role))
    staff = new_client()
    assert login(staff, username="staff.member", password=STAFF_PASSWORD).status_code == 200

    responses = [
        staff.get(TABLES_URL),
        create_table(staff, "Intrusa"),
        staff.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False}),
        staff.post(f"{TABLES_URL}/{table['id']}/pin"),
    ]

    assert [response.status_code for response in responses] == [403] * 4


def test_anonymous_callers_get_401(new_client: ClientFactory) -> None:
    assert new_client().get(TABLES_URL).status_code == 401


# --- Done when: "Desactivar la mesa o regenerar su PIN cierra la sesión del dispositivo." --------


def test_deactivating_a_table_ends_its_device_session_at_once(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    refresh_token = tablet.cookies.get("refresh_token")

    response = admin.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert tablet.get("/api/v1/auth/me").status_code == 401
    assert refresh_with(new_client(), refresh_token).status_code == 401
    assert table_login(new_client(), table["code"], table["pin"]).status_code == 401


def test_regenerating_the_pin_ends_the_device_session_and_only_the_new_pin_works(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    tablet = tablet_of(new_client, table)
    refresh_token = tablet.cookies.get("refresh_token")

    response = admin.post(f"{TABLES_URL}/{table['id']}/pin")

    assert response.status_code == 200
    regenerated = response.json()
    assert regenerated["code"] == table["code"]
    assert re.fullmatch(r"\d{6}", regenerated["pin"])
    assert tablet.get("/api/v1/auth/me").status_code == 401
    assert refresh_with(new_client(), refresh_token).status_code == 401
    if regenerated["pin"] != table["pin"]:
        assert table_login(new_client(), table["code"], table["pin"]).status_code == 401
    assert table_login(new_client(), table["code"], regenerated["pin"]).status_code == 200


def test_a_refresh_token_that_escaped_the_pin_change_still_cannot_refresh(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    refresh_token = tablet_of(new_client, table).cookies.get("refresh_token")

    assert admin.post(f"{TABLES_URL}/{table['id']}/pin").status_code == 200
    unrevoke_refresh_tokens(table_id=uuid.UUID(table["id"]))

    assert refresh_with(new_client(), refresh_token).status_code == 401


def test_an_access_token_signed_after_the_pin_change_for_the_old_session_is_rejected(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    # A login or refresh that read the table before the change committed can still sign a token after it.
    admin = admin_of(new_client)
    table = created(create_table(admin))
    assert admin.post(f"{TABLES_URL}/{table['id']}/pin").status_code == 200

    def token(session_version: int) -> str:
        claims = claims_for(uuid.UUID(table["id"]), tenant_a.tenant_id, "table", table_id=table["id"])
        return sign({**claims, "iat": datetime.now(UTC) + timedelta(seconds=2), "sv": session_version})

    assert me(new_client(), token(1)).status_code == 401
    assert me(new_client(), token(2)).status_code == 200


# --- Tenant isolation --------------------------------------------------------------------------


def test_a_tenant_never_sees_nor_changes_another_tenant_tables(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    owner = admin_of(new_client)
    table = created(create_table(owner))
    tablet = tablet_of(new_client, table)
    other = admin_of(new_client, "boss@example.com")

    assert other.get(TABLES_URL).json() == []
    assert other.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False}).status_code == 404
    assert other.post(f"{TABLES_URL}/{table['id']}/pin").status_code == 404
    assert owner.get(TABLES_URL).json()[0]["is_active"] is True
    assert tablet.get("/api/v1/auth/me").json()["tenant"]["id"] == str(tenant_a.tenant_id)


def test_repeating_a_table_create_never_makes_a_second_table(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    import uuid

    admin = admin_of(new_client)
    body = {"id": str(uuid.uuid4()), "name": "Mesa 7"}

    first = admin.post(TABLES_URL, json=body)
    replay = admin.post(TABLES_URL, json=body)

    assert first.status_code == 201 and first.json()["id"] == body["id"]
    assert replay.status_code == 409
    assert replay.json()["detail"] == "This table was already created; generate a new PIN to see its credentials"
    assert [t["name"] for t in admin.get(TABLES_URL).json()] == ["Mesa 7"]
    # Unknown fields are rejected, not silently ignored.
    assert admin.post(TABLES_URL, json={"name": "Mesa 8", "tenant_id": "x"}).status_code == 422
    assert admin.patch(f"{TABLES_URL}/{body['id']}", json={"code": "HACKED"}).status_code == 422
