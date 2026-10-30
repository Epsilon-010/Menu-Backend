"""Admin use cases over the tenant's library of modifier groups.

Another tenant's groups are reported as not found; deleting a group detaches it from every item.
"""

import uuid
from dataclasses import dataclass

from app.modules.catalog.domain.errors import CatalogIdTaken, InvalidCatalogData, ModifierGroupNotFound
from app.modules.catalog.domain.modifiers import ModifierGroup, ModifierGroupRepository, OptionDraft
from app.shared.domain.ports import UnitOfWork


@dataclass(frozen=True)
class ModifierGroupDraft:
    name: str
    min_select: int
    max_select: int
    options: tuple[OptionDraft, ...]
    # Sent by the client to make the create idempotent; None generates one.
    id: uuid.UUID | None = None


@dataclass(frozen=True)
class ModifierGroupChanges:
    """Fields left as None keep their value; `options` is the whole new list in order."""

    name: str | None = None
    min_select: int | None = None
    max_select: int | None = None
    options: tuple[OptionDraft, ...] | None = None


async def get_group(
    groups: ModifierGroupRepository, tenant_id: uuid.UUID, group_id: uuid.UUID, for_update: bool = False
) -> ModifierGroup:
    load = groups.get_for_update if for_update else groups.get
    group = await load(tenant_id, group_id)
    if group is None:
        raise ModifierGroupNotFound(group_id)
    return group


async def ensure_groups_exist(
    groups: ModifierGroupRepository, tenant_id: uuid.UUID, group_ids: tuple[uuid.UUID, ...]
) -> None:
    """Every group an item will use belongs to the tenant, and stays until the item is saved."""
    if group_ids and await groups.lock_existing(tenant_id, group_ids) != set(group_ids):
        raise InvalidCatalogData("Unknown modifier group")


class ListModifierGroups:
    def __init__(self, groups: ModifierGroupRepository) -> None:
        self._groups = groups

    async def execute(self, tenant_id: uuid.UUID) -> list[ModifierGroup]:
        return await self._groups.list(tenant_id)


class CreateModifierGroup:
    """Idempotent when the client sends the id: repeating the same create returns the same group."""

    def __init__(self, groups: ModifierGroupRepository, uow: UnitOfWork) -> None:
        self._groups = groups
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, draft: ModifierGroupDraft) -> ModifierGroup:
        group = ModifierGroup.create(
            tenant_id, draft.name, draft.min_select, draft.max_select, draft.options, draft.id
        )
        if draft.id is not None:
            # Taken before the replay check, so a concurrent replay waits and then finds the first one.
            await self._groups.lock_id(draft.id)
            existing = await self._groups.get(tenant_id, draft.id)
            if existing is not None:
                if not existing.same_draft(draft.name, draft.min_select, draft.max_select, draft.options):
                    raise CatalogIdTaken(draft.id)
                return existing
            if await self._groups.exists_anywhere(draft.id):
                raise CatalogIdTaken(draft.id)
        await self._groups.add(group)
        await self._uow.commit()
        return group


class UpdateModifierGroup:
    """Edits a group; options keep their id when listed with it, so carts keep pointing at them."""

    def __init__(self, groups: ModifierGroupRepository, uow: UnitOfWork) -> None:
        self._groups = groups
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, group_id: uuid.UUID, changes: ModifierGroupChanges) -> ModifierGroup:
        group = await get_group(self._groups, tenant_id, group_id, for_update=True)
        updated = group.with_changes(
            name=changes.name,
            min_select=changes.min_select,
            max_select=changes.max_select,
            options=changes.options,
        )
        await self._groups.update(updated)
        await self._uow.commit()
        return updated


class DeleteModifierGroup:
    def __init__(self, groups: ModifierGroupRepository, uow: UnitOfWork) -> None:
        self._groups = groups
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, group_id: uuid.UUID) -> None:
        await get_group(self._groups, tenant_id, group_id, for_update=True)
        await self._groups.delete(tenant_id, group_id)
        await self._uow.commit()
