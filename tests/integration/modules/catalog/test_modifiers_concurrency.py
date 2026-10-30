"""Races on the modifier library: they must end in a clear answer (never a 500 or a deadlock) and consistent rows."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.catalog.application.manage_categories import CreateCategory
from app.modules.catalog.application.manage_items import CreateItem, ItemChanges, ItemDraft, UpdateItem
from app.modules.catalog.application.manage_modifiers import (
    CreateModifierGroup,
    DeleteModifierGroup,
    ListModifierGroups,
    ModifierGroupDraft,
)
from app.modules.catalog.domain.errors import InvalidCatalogData
from app.modules.catalog.domain.modifiers import OptionDraft
from app.modules.catalog.infrastructure.repository import (
    SqlAlchemyCategoryRepository,
    SqlAlchemyItemRepository,
    SqlAlchemyModifierGroupRepository,
)
from app.seed import SeedResult
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork
from tests.integration.modules.catalog.test_catalog_concurrency import PAUSE, SlowItems, _in_session, _run, tenant  # noqa: F401

DRAFT = ModifierGroupDraft(
    name="Size", min_select=1, max_select=1, options=(OptionDraft("Small", 0), OptionDraft("Large", 1500))
)


class SlowGroups(SqlAlchemyModifierGroupRepository):
    async def get(self, *args: Any) -> Any:
        found = await super().get(*args)
        await asyncio.sleep(PAUSE)
        return found

    async def get_for_update(self, *args: Any) -> Any:
        found = await super().get_for_update(*args)
        await asyncio.sleep(PAUSE)
        return found


def _groups(session: AsyncSession) -> SqlAlchemyModifierGroupRepository:
    return SqlAlchemyModifierGroupRepository(session)


def test_concurrent_replays_of_one_create_make_a_single_group(tenant: SeedResult) -> None:
    group_id = uuid.uuid4()

    async def create(session: AsyncSession) -> uuid.UUID:
        use_case = CreateModifierGroup(SlowGroups(session), SqlAlchemyUnitOfWork(session))
        return (await use_case.execute(tenant.tenant_id, ModifierGroupDraft(**{**DRAFT.__dict__, "id": group_id}))).id

    async def work(factory: async_sessionmaker[AsyncSession]) -> tuple[list[uuid.UUID], int]:
        ids = await asyncio.gather(*(_in_session(factory, create) for _ in range(3)))
        listed = await _in_session(factory, lambda s: ListModifierGroups(_groups(s)).execute(tenant.tenant_id))
        return list(ids), len(listed)

    assert _run(work) == ([group_id] * 3, 1)


@pytest.mark.parametrize("delete_first", [False, True])
def test_linking_a_group_while_it_is_deleted_never_fails_with_a_server_error(
    tenant: SeedResult, delete_first: bool
) -> None:
    """The item already uses the group (its link row is rewritten) while the group is deleted."""

    async def work(factory: async_sessionmaker[AsyncSession]) -> tuple[list[Any], tuple[uuid.UUID, ...], int, uuid.UUID]:
        async def setup(s: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
            uow = SqlAlchemyUnitOfWork(s)
            size = await CreateModifierGroup(_groups(s), uow).execute(tenant.tenant_id, DRAFT)
            extras = await CreateModifierGroup(_groups(s), uow).execute(
                tenant.tenant_id, ModifierGroupDraft(**{**DRAFT.__dict__, "name": "Extras", "min_select": 0})
            )
            category = await CreateCategory(SqlAlchemyCategoryRepository(s), uow).execute(tenant.tenant_id, "Tacos")
            draft = ItemDraft(
                category_id=category.id, name="Pastor", description="", price_cents=2500, modifier_group_ids=(size.id,)
            )
            item = await CreateItem(SqlAlchemyCategoryRepository(s), SqlAlchemyItemRepository(s), _groups(s), uow).execute(
                tenant.tenant_id, draft
            )
            return item.id, size.id, extras.id

        item_id, size_id, extras_id = await _in_session(factory, setup)

        async def relink(s: AsyncSession) -> Any:
            if delete_first:
                await asyncio.sleep(PAUSE / 3)
            use_case = UpdateItem(SqlAlchemyCategoryRepository(s), SlowItems(s), _groups(s), SqlAlchemyUnitOfWork(s))
            return await use_case.execute(tenant.tenant_id, item_id, ItemChanges(modifier_group_ids=(extras_id, size_id)))

        async def delete(s: AsyncSession) -> None:
            if not delete_first:
                await asyncio.sleep(PAUSE / 3)
            await DeleteModifierGroup(SlowGroups(s), SqlAlchemyUnitOfWork(s)).execute(tenant.tenant_id, size_id)

        outcomes = await asyncio.wait_for(
            asyncio.gather(_in_session(factory, relink), _in_session(factory, delete), return_exceptions=True), 20
        )
        final = await _in_session(factory, lambda s: SqlAlchemyItemRepository(s).get(tenant.tenant_id, item_id))
        left = await _in_session(factory, lambda s: ListModifierGroups(_groups(s)).execute(tenant.tenant_id))
        assert final is not None
        return list(outcomes), final.modifier_group_ids, len(left), extras_id

    outcomes, group_ids, groups_left, extras_id = _run(work)

    relinked, deleted = outcomes
    assert deleted is None
    assert groups_left == 1
    # Either the relink ran first (the delete then detached it) or it saw the group gone.
    if isinstance(relinked, BaseException):
        assert isinstance(relinked, InvalidCatalogData) and str(relinked) == "Unknown modifier group"
        assert group_ids == ()
    else:
        assert group_ids == (extras_id,)
