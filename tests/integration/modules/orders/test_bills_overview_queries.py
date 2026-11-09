"""The staff overview costs the same number of queries however many tables are open, and open bills use an index."""

import asyncio

from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine
from sqlalchemy import text
from tests.integration.modules.orders.test_kitchen_api import send_order
from tests.integration.modules.orders.test_ordering_api import menu_items, staff_of, tables_overview
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
from tests.integration.query_log import recorded_statements


def _queries_for_overview(staff) -> int:  # type: ignore[no-untyped-def]
    with recorded_statements() as statements:
        tables_overview(staff)
    return len(statements)


def test_the_overview_makes_no_query_per_table(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    item = menu_items(admin)["pastor"]
    waiter = staff_of(new_client, admin, "waiter.queries", "waiter")
    send_order(tablet_of(new_client, created(create_table(admin, "Mesa 1"))), item, 1)
    with_one_table = _queries_for_overview(waiter)

    for n in range(2, 6):
        send_order(tablet_of(new_client, created(create_table(admin, f"Mesa {n}"))), item, 1)

    assert _queries_for_overview(waiter) == with_one_table


def test_the_overview_keeps_each_bill_with_its_own_orders_in_order(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin = admin_of(new_client)
    item = menu_items(admin)["pastor"]
    waiter = staff_of(new_client, admin, "waiter.queries", "waiter")
    first = tablet_of(new_client, created(create_table(admin, "Mesa 1")))
    second = tablet_of(new_client, created(create_table(admin, "Mesa 2")))
    send_order(first, item, 1)
    send_order(second, item, 2)
    send_order(first, item, 3)

    overview = {row["table_name"]: row["bill"] for row in tables_overview(waiter)}

    assert [o["number"] for o in overview["Mesa 1"]["orders"]] == [1, 3]
    assert [o["number"] for o in overview["Mesa 2"]["orders"]] == [2]
    assert overview["Mesa 1"]["total_cents"] == 2500 * 4
    assert overview["Mesa 2"]["total_cents"] == 2500 * 2


def test_a_tenant_overview_never_mixes_in_another_tenant_bills(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    item = menu_items(admin)["pastor"]
    send_order(tablet_of(new_client, created(create_table(admin, "Mesa 1"))), item, 1)

    other = admin_of(new_client, "boss@example.com")
    other_item = menu_items(other)["pastor"]
    send_order(tablet_of(new_client, created(create_table(other, "Terraza"))), other_item, 2)

    mine = tables_overview(admin)
    theirs = tables_overview(other)

    assert [(row["table_name"], row["bill"]["total_cents"]) for row in mine] == [("Mesa 1", 2500)]
    assert [(row["table_name"], row["bill"]["total_cents"]) for row in theirs] == [("Terraza", 5000)]


def test_open_bills_are_found_through_a_partial_index() -> None:
    async def definition() -> str | None:
        engine = create_engine(get_settings().database_url)
        try:
            async with engine.connect() as connection:
                return await connection.scalar(
                    text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_bills_open_tenant_id'")
                )
        finally:
            await engine.dispose()

    index = asyncio.run(definition())

    assert index is not None
    assert "(tenant_id)" in index
    assert "WHERE (closed_at IS NULL)" in index
