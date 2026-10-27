"""Guarantees the database keeps even when a use case's checks are bypassed or raced."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.domain.catalog import Category, Item
from app.modules.catalog.domain.errors import CategoryNotEmpty
from app.modules.catalog.infrastructure.models import CategoryModel, ItemModel
from app.modules.catalog.infrastructure.repository import SqlAlchemyCategoryRepository, SqlAlchemyItemRepository
from app.modules.tenants.infrastructure.models import TenantModel
from app.seed import SeedResult
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from tests.integration.modules.auth.test_auth_api import _seed

T = TypeVar("T")


def _in_session(work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def run() -> T:
        engine = create_engine(get_settings().database_url)
        try:
            async with create_session_factory(engine)() as session:
                result = await work(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def tenants() -> tuple[SeedResult, SeedResult]:
    return asyncio.run(_seed("La Taquería", "owner@example.com")), asyncio.run(_seed("Burger Place", "boss@example.com"))


def _add_category(tenant_id: uuid.UUID) -> Category:
    category = Category.create(tenant_id, "Tacos", 0)
    _in_session(lambda session: SqlAlchemyCategoryRepository(session).add(category))
    return category


def _add_item(tenant_id: uuid.UUID, category_id: uuid.UUID) -> Item:
    item = Item.create(tenant_id, category_id, "Pastor", "", 2500, 0)
    _in_session(lambda session: SqlAlchemyItemRepository(session).add(item))
    return item


def test_an_item_cannot_point_to_another_tenant_category(tenants: tuple[SeedResult, SeedResult]) -> None:
    tenant_a, tenant_b = tenants
    foreign = _add_category(tenant_b.tenant_id)

    with pytest.raises(IntegrityError):
        _add_item(tenant_a.tenant_id, foreign.id)


def test_a_category_with_items_is_never_deleted(tenants: tuple[SeedResult, SeedResult]) -> None:
    tenant_id = tenants[0].tenant_id
    category = _add_category(tenant_id)
    _add_item(tenant_id, category.id)

    with pytest.raises(CategoryNotEmpty):
        _in_session(lambda session: SqlAlchemyCategoryRepository(session).delete(tenant_id, category.id))

    assert _in_session(lambda session: SqlAlchemyCategoryRepository(session).get(tenant_id, category.id)) == category


def test_deleting_a_tenant_removes_its_catalog(tenants: tuple[SeedResult, SeedResult]) -> None:
    tenant_id = tenants[0].tenant_id
    _add_item(tenant_id, _add_category(tenant_id).id)
    _add_item(tenants[1].tenant_id, _add_category(tenants[1].tenant_id).id)

    _in_session(lambda session: session.execute(delete(TenantModel).where(TenantModel.id == tenant_id)))

    async def count(session: AsyncSession) -> tuple[int | None, int | None]:
        return (
            await session.scalar(select(func.count()).select_from(CategoryModel)),
            await session.scalar(select(func.count()).select_from(ItemModel)),
        )

    assert _in_session(count) == (1, 1)
