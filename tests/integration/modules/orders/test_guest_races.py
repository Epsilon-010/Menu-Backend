"""Races between the admin changing a table (new QR, deactivation) and the people sitting at it.

Both sides take the table's visit lock before any row lock, so neither deadlocks, and a QR scan that
waited for a new QR re-checks the token once it gets the lock."""

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from httpx import Response
from sqlalchemy import func, select, text

from app.modules.orders.infrastructure.repository import SqlAlchemyCartRepository
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine
from tests.integration.modules.catalog.test_catalog_api import ok
from tests.integration.modules.orders.test_guest_qr_api import guest_of, open_table, scan
from tests.integration.modules.orders.test_ordering_api import CART_URL, add, menu_items
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    TABLES_URL,
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tenant_a,
)


def in_background(call: Callable[[], Response]) -> tuple[threading.Thread, list[Response]]:
    results: list[Response] = []
    thread = threading.Thread(target=lambda: results.append(call()))
    thread.start()
    return thread, results


def test_a_scan_of_the_old_qr_waiting_on_a_new_qr_is_refused(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    table = created(create_table(admin))
    open_table(admin, table)
    phone = new_client()

    async def regenerate_while_the_scan_waits() -> Response:
        # Plays RegenerateTableQr getting the table lock first: the scan must wait for it.
        engine = create_engine(get_settings().database_url)
        async with engine.connect() as conn:
            key = f"table-visit:{tenant_a.tenant_id}:{table['id']}"
            await conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
            thread, results = in_background(lambda: scan(phone, table["qr_token"]))
            await asyncio.sleep(0.5)
            await conn.execute(
                text("UPDATE tables SET qr_token = 'brand-new-qr-token' WHERE id = :id"), {"id": table["id"]}
            )
            await conn.commit()
        await engine.dispose()
        thread.join()
        return results[0]

    scanned = asyncio.run(regenerate_while_the_scan_waits())

    assert (scanned.status_code, scanned.json()["detail"]) == (401, "This QR code is not valid")
    assert phone.get(CART_URL).status_code == 401


@pytest.mark.parametrize(
    "admin_change",
    [
        lambda admin, table: admin.post(f"{TABLES_URL}/{table['id']}/qr"),
        lambda admin, table: admin.patch(f"{TABLES_URL}/{table['id']}", json={"is_active": False}),
    ],
    ids=["new-qr", "deactivate"],
)
def test_changing_a_table_while_a_guest_adds_never_deadlocks(
    new_client: ClientFactory,
    tenant_a: SeedResult,
    monkeypatch: pytest.MonkeyPatch,
    admin_change: Callable[[Any, dict[str, str]], Response],
) -> None:
    admin = admin_of(new_client)
    items = menu_items(admin)
    table = created(create_table(admin))
    open_table(admin, table)
    guest = guest_of(new_client, table["qr_token"])
    original_add_line = SqlAlchemyCartRepository.add_line

    async def slow_add_line(self: SqlAlchemyCartRepository, line: Any) -> None:
        # The guest holds the table lock while the admin's request arrives.
        await asyncio.sleep(0.6)
        await original_add_line(self, line)

    monkeypatch.setattr(SqlAlchemyCartRepository, "add_line", slow_add_line)
    thread, results = in_background(lambda: add(guest, items["pastor"]))
    time.sleep(0.25)

    changed = admin_change(admin, table)
    thread.join()

    assert changed.status_code == 200, changed.text
    # The guest's add went first and succeeded; the change then ended their visit.
    assert results[0].status_code == 200, results[0].text
    assert guest.get(CART_URL).status_code == 401
    assert ok(changed)["id"] == table["id"]
