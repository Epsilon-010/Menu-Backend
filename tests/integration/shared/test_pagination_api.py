"""Cursor pagination of the admin lists: GET /staff, /admins, /tables and /catalog/modifier-groups."""

import base64
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.staff.test_staff_api import (  # noqa: F401  (fixtures)
    ClientFactory,
    add_member,
    new_client,
    signed_in,
    tenant_a,
    tenant_b,
)

Json = dict[str, Any]

STAFF_URL = "/api/v1/staff"
ADMINS_URL = "/api/v1/admins"
TABLES_URL = "/api/v1/tables"
GROUPS_URL = "/api/v1/catalog/modifier-groups"


def _add_staff(admin: TestClient, name: str) -> None:
    assert add_member(admin, name).status_code == 201


def _add_admin(admin: TestClient, name: str) -> None:
    email = f"{name.lower().replace(' ', '.')}@example.com"
    response = admin.post(ADMINS_URL, json={"full_name": name, "email": email})
    assert response.status_code == 201, response.text


def _add_table(admin: TestClient, name: str) -> None:
    assert admin.post(TABLES_URL, json={"name": name}).status_code == 201


def _add_group(admin: TestClient, name: str) -> None:
    body = {"name": name, "min_select": 0, "max_select": 1, "options": [{"name": "Plain", "price_cents": 0}]}
    assert admin.post(GROUPS_URL, json=body).status_code == 201


Adder = Callable[[TestClient, str], None]
# (url, adder, field holding the sort name, rows that exist before the test adds any)
LISTS: list[tuple[str, Adder, str, int]] = [
    (STAFF_URL, _add_staff, "full_name", 0),
    (ADMINS_URL, _add_admin, "full_name", 1),  # the owner
    (TABLES_URL, _add_table, "name", 0),
    (GROUPS_URL, _add_group, "name", 0),
]
IDS = ["staff", "admins", "tables", "modifier-groups"]


def _page(client: TestClient, url: str, **params: Any) -> Json:
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    body: Json = response.json()
    assert set(body) == {"items", "next_cursor"}
    return body


def _walk(client: TestClient, url: str, limit: int) -> list[list[Json]]:
    pages: list[list[Json]] = []
    cursor: str | None = None
    while True:
        body = _page(client, url, limit=limit, **({"cursor": cursor} if cursor else {}))
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages


@pytest.mark.parametrize(("url", "add", "field", "existing"), LISTS, ids=IDS)
def test_pages_cover_every_row_once_in_name_order(
    new_client: ClientFactory, tenant_a: SeedResult, url: str, add: Adder, field: str, existing: int
) -> None:
    admin = signed_in(new_client, tenant_a.email)
    # Repeated names where the list allows them (tables and admin emails are unique): the id breaks
    # the tie, so no row is skipped or repeated.
    repeated = "alpha" if url in (STAFF_URL, GROUPS_URL) else "alpha two"
    for name in ["delta", "Alpha", "charlie", "Bravo", repeated, "echo"]:
        add(admin, name)

    pages = _walk(admin, url, limit=2)
    rows = [row for page in pages for row in page]

    assert [len(page) for page in pages][:-1] == [2] * (len(pages) - 1)
    assert len(rows) == 6 + existing
    assert len({row["id"] for row in rows}) == len(rows)
    names = [row[field].lower() for row in rows]
    assert names == sorted(names)
    assert rows == _page(admin, url, limit=100)["items"]


@pytest.mark.parametrize(("url", "add", "field", "existing"), LISTS, ids=IDS)
def test_default_page_size_is_50_and_last_page_has_no_cursor(
    new_client: ClientFactory, tenant_a: SeedResult, url: str, add: Adder, field: str, existing: int
) -> None:
    admin = signed_in(new_client, tenant_a.email)
    add(admin, "Only")

    body = _page(admin, url)

    assert len(body["items"]) == 1 + existing
    assert body["next_cursor"] is None


@pytest.mark.parametrize(("url", "add", "field", "existing"), LISTS, ids=IDS)
@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc"])
def test_limit_outside_1_to_100_is_rejected(
    new_client: ClientFactory, tenant_a: SeedResult, url: str, add: Adder, field: str, existing: int, limit: str
) -> None:
    admin = signed_in(new_client, tenant_a.email)

    response = admin.get(url, params={"limit": limit})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


def _forged(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize(("url", "add", "field", "existing"), LISTS, ids=IDS)
@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-cursor",
        "%%%",
        _forged(["name"]),
        _forged(["name", "not-a-uuid"]),
        _forged({"k": "name"}),
        _forged([1, "00000000-0000-0000-0000-000000000000"]),
        _forged(["x" * 300, "00000000-0000-0000-0000-000000000000"]),
        "A" * 600,
    ],
)
def test_malformed_cursor_is_rejected(
    new_client: ClientFactory,
    tenant_a: SeedResult,
    url: str,
    add: Adder,
    field: str,
    existing: int,
    cursor: str,
) -> None:
    admin = signed_in(new_client, tenant_a.email)

    response = admin.get(url, params={"cursor": cursor})

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid cursor"


@pytest.mark.parametrize(("url", "add", "field", "existing"), LISTS, ids=IDS)
def test_a_cursor_never_reaches_another_tenant(
    new_client: ClientFactory,
    tenant_a: SeedResult,
    tenant_b: SeedResult,
    url: str,
    add: Adder,
    field: str,
    existing: int,
) -> None:
    admin_a = signed_in(new_client, tenant_a.email)
    admin_b = signed_in(new_client, tenant_b.email)
    for name in ["a1", "a2", "a3"]:
        add(admin_a, name)
    add(admin_b, "b9")
    cursor = _page(admin_a, url, limit=1)["next_cursor"]

    body = _page(admin_b, url, cursor=cursor)

    # B's cursor-moved page only holds B's rows (b9 sorts after "a1").
    assert "b9" in [row[field] for row in body["items"]]
    a_ids = {row["id"] for row in _page(admin_a, url, limit=100)["items"]}
    assert not a_ids & {row["id"] for row in body["items"]}
