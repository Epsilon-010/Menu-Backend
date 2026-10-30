"""Slice 16 S1/S8: each business has its own time zone; only its admin reads and changes it."""

import pytest
from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.auth.test_register_api import register
from tests.integration.modules.catalog.test_catalog_api import ok
from tests.integration.modules.orders.test_ordering_api import staff_of
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tablet_of,
    tenant_a,
    tenant_b,
)

SETTINGS_URL = "/api/v1/tenant/settings"


def test_a_seeded_business_starts_in_the_default_zone_and_its_admin_changes_it(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    assert ok(admin.get(SETTINGS_URL)) == {"timezone": "America/Mexico_City"}

    assert ok(admin.patch(SETTINGS_URL, json={"timezone": "America/Bogota"})) == {"timezone": "America/Bogota"}

    assert ok(admin.get(SETTINGS_URL)) == {"timezone": "America/Bogota"}


@pytest.mark.parametrize("zone", ["Mars/Olympus", "", "Etc/../../passwd"])
def test_an_unknown_zone_is_422_and_changes_nothing(
    new_client: ClientFactory, tenant_a: SeedResult, zone: str
) -> None:
    admin = admin_of(new_client)

    refused = admin.patch(SETTINGS_URL, json={"timezone": zone})

    assert refused.status_code == 422
    assert refused.json()["detail"] == "Unknown time zone"
    assert ok(admin.get(SETTINGS_URL)) == {"timezone": "America/Mexico_City"}


@pytest.mark.parametrize("body", [{}, {"timezone": 5}, {"timezone": "UTC", "extra": 1}, {"timezone": "x" * 65}])
def test_a_malformed_body_is_422(new_client: ClientFactory, tenant_a: SeedResult, body: dict[str, object]) -> None:
    assert admin_of(new_client).patch(SETTINGS_URL, json=body).status_code == 422


def test_sign_up_stores_the_zone_sent_by_the_browser(new_client: ClientFactory) -> None:
    owner = new_client()
    assert register(owner, timezone="Europe/Madrid").status_code == 201

    assert ok(owner.get(SETTINGS_URL)) == {"timezone": "Europe/Madrid"}


def test_sign_up_without_a_zone_uses_the_default(new_client: ClientFactory) -> None:
    owner = new_client()
    assert register(owner).status_code == 201

    assert ok(owner.get(SETTINGS_URL)) == {"timezone": "America/Mexico_City"}


def test_sign_up_with_an_unknown_zone_is_422_and_creates_nothing(new_client: ClientFactory) -> None:
    owner = new_client()

    refused = register(owner, timezone="Mars/Olympus")

    assert refused.status_code == 422
    assert refused.json()["detail"] == "Unknown time zone"
    assert register(owner).status_code == 201


def test_each_business_keeps_its_own_zone(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    ok(admin_of(new_client).patch(SETTINGS_URL, json={"timezone": "Asia/Tokyo"}))

    assert ok(admin_of(new_client, "boss@example.com").get(SETTINGS_URL)) == {"timezone": "America/Mexico_City"}


def test_only_the_admin_reads_or_changes_the_zone(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    others: list[TestClient] = [
        staff_of(new_client, admin, "waiter.tz", "waiter"),
        staff_of(new_client, admin, "cook.tz", "kitchen"),
        tablet_of(new_client, created(create_table(admin, "Mesa TZ"))),
    ]

    for other in others:
        assert other.get(SETTINGS_URL).status_code == 403
        assert other.patch(SETTINGS_URL, json={"timezone": "UTC"}).status_code == 403
    assert ok(admin.get(SETTINGS_URL)) == {"timezone": "America/Mexico_City"}
