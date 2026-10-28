"""Adapters from the ordering ports to the other modules' application layers, auth's revocations and Redis."""

import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.menu import GetOrderableItems
from app.modules.catalog.infrastructure.repository import SqlAlchemyCategoryRepository, SqlAlchemyItemRepository
from app.modules.orders.domain.ports import MenuItem, TableInfo
from app.modules.tables.application.find_table import GetTable
from app.modules.tables.application.manage_tables import ListTables
from app.modules.tables.infrastructure.repository import SqlAlchemyTableRepository

logger = logging.getLogger(__name__)

# Enough history for a client that reconnects within a few seconds; older clients reload from the API.
_STREAM_LENGTH = 1000


def table_events_stream(tenant_id: uuid.UUID) -> str:
    return f"orders:{tenant_id}"


class CatalogMenu:
    def __init__(self, session: AsyncSession) -> None:
        self._items = GetOrderableItems(SqlAlchemyCategoryRepository(session), SqlAlchemyItemRepository(session))

    async def orderable(self, tenant_id: uuid.UUID, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, MenuItem]:
        return {
            item_id: MenuItem(item_id=item_id, name=item.name, price_cents=item.price_cents)
            for item_id, item in (await self._items.execute(tenant_id, item_ids)).items()
        }


class TablesModule:
    def __init__(self, session: AsyncSession) -> None:
        tables = SqlAlchemyTableRepository(session)
        self._get = GetTable(tables)
        self._list = ListTables(tables)

    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> TableInfo | None:
        table = await self._get.execute(tenant_id, table_id)
        if table is None:
            return None
        return TableInfo(
            name=table.name, is_active=table.is_active, session_version=table.session_version, qr_token=table.qr_token
        )

    async def list_active(self, tenant_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
        return [(table.id, table.name) for table in await self._list.execute(tenant_id) if table.is_active]


class RedisTableEvents:
    """One Redis Stream per tenant (`orders:{tenant_id}`); failures are logged, never raised: the
    change is already committed and clients reload it from the API."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(
        self,
        tenant_id: uuid.UUID,
        table_id: uuid.UUID,
        kind: str,
        cart_version: int | None = None,
        order_id: uuid.UUID | None = None,
    ) -> None:
        fields = {"kind": kind, "table_id": str(table_id)}
        if cart_version is not None:
            fields["cart_version"] = str(cart_version)
        if order_id is not None:
            fields["order_id"] = str(order_id)
        try:
            await self._redis.xadd(table_events_stream(tenant_id), fields, maxlen=_STREAM_LENGTH, approximate=True)  # type: ignore[arg-type]
        except RedisError:
            logger.warning("Could not publish %s for table %s", kind, table_id, exc_info=True)
