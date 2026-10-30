"""Modifier groups: a tenant library of choices (size, extras, salsas) that items reuse.

A group says how many of its options a guest picks (`min_select` to `max_select`, each option at
most once); options add zero or more cents to the item's price and can be sold out.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.modules.catalog.domain.catalog import validate_price
from app.modules.catalog.domain.errors import InvalidCatalogData

MAX_GROUP_NAME_LENGTH = 80
MAX_OPTION_NAME_LENGTH = 80
MAX_OPTIONS_PER_GROUP = 30


def validate_group_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > MAX_GROUP_NAME_LENGTH:
        raise InvalidCatalogData(f"Group name must have 1 to {MAX_GROUP_NAME_LENGTH} characters")
    return name


def validate_option_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > MAX_OPTION_NAME_LENGTH:
        raise InvalidCatalogData(f"Option name must have 1 to {MAX_OPTION_NAME_LENGTH} characters")
    return name


@dataclass(frozen=True)
class OptionDraft:
    """An option as the admin sends it; `id` keeps an existing option (cart lines point at it)."""

    name: str
    price_cents: int
    is_available: bool = True
    id: uuid.UUID | None = None


@dataclass(frozen=True)
class ModifierOption:
    name: str
    price_cents: int
    is_available: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def _options(drafts: Sequence[OptionDraft], known_ids: set[uuid.UUID] | None) -> tuple[ModifierOption, ...]:
    """`known_ids` None means a new group (ids are free to choose); otherwise only its own ids are allowed."""
    if not 1 <= len(drafts) <= MAX_OPTIONS_PER_GROUP:
        raise InvalidCatalogData(f"A group must have 1 to {MAX_OPTIONS_PER_GROUP} options")
    given = [draft.id for draft in drafts if draft.id is not None]
    if len(given) != len(set(given)) or (known_ids is not None and not set(given) <= known_ids):
        raise InvalidCatalogData("Unknown option")
    options = tuple(
        ModifierOption(
            name=validate_option_name(draft.name),
            price_cents=validate_price(draft.price_cents),
            is_available=draft.is_available,
            id=draft.id or uuid.uuid4(),
        )
        for draft in drafts
    )
    if len({option.name.lower() for option in options}) != len(options):
        raise InvalidCatalogData("Option names must be unique in a group")
    return options


def _check_limits(min_select: int, max_select: int, option_count: int) -> None:
    if not 0 <= min_select <= max_select or not 1 <= max_select <= option_count:
        raise InvalidCatalogData("Invalid selection limits")


@dataclass(frozen=True)
class ModifierGroup:
    tenant_id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    options: tuple[ModifierOption, ...]
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(
        cls,
        tenant_id: uuid.UUID,
        name: str,
        min_select: int,
        max_select: int,
        options: Sequence[OptionDraft],
        group_id: uuid.UUID | None = None,
    ) -> "ModifierGroup":
        """`group_id` comes from the client to make the create idempotent; None generates one."""
        built = _options(options, None)
        _check_limits(min_select, max_select, len(built))
        return cls(
            tenant_id=tenant_id,
            name=validate_group_name(name),
            min_select=min_select,
            max_select=max_select,
            options=built,
            id=group_id or uuid.uuid4(),
        )

    def same_draft(self, name: str, min_select: int, max_select: int, options: Sequence[OptionDraft]) -> bool:
        """Whether a repeated create asks for exactly this group (after the same normalization)."""
        if len(options) != len(self.options):
            return False
        same_options = all(
            (option.name, option.price_cents, option.is_available) == (draft.name.strip(), draft.price_cents, draft.is_available)
            and draft.id in (None, option.id)
            for option, draft in zip(self.options, options, strict=True)
        )
        return same_options and (self.name, self.min_select, self.max_select) == (name.strip(), min_select, max_select)

    def with_changes(
        self,
        name: str | None = None,
        min_select: int | None = None,
        max_select: int | None = None,
        options: Sequence[OptionDraft] | None = None,
    ) -> "ModifierGroup":
        built = self.options if options is None else _options(options, {option.id for option in self.options})
        updated = replace(
            self,
            name=self.name if name is None else validate_group_name(name),
            min_select=self.min_select if min_select is None else min_select,
            max_select=self.max_select if max_select is None else max_select,
            options=built,
        )
        _check_limits(updated.min_select, updated.max_select, len(built))
        return updated

    def can_be_met(self) -> bool:
        """Whether enough options are available to fill the group's minimum."""
        return sum(option.is_available for option in self.options) >= self.min_select


class ModifierGroupRepository(Protocol):
    async def add(self, group: ModifierGroup) -> None:
        """Raises CatalogIdTaken if the group's or an option's id already exists."""
        ...

    async def get(self, tenant_id: uuid.UUID, group_id: uuid.UUID) -> ModifierGroup | None: ...

    async def get_for_update(self, tenant_id: uuid.UUID, group_id: uuid.UUID) -> ModifierGroup | None:
        """Same as `get`, locking the row until the transaction ends: for every read-then-write."""
        ...

    async def exists_anywhere(self, group_id: uuid.UUID) -> bool:
        """Whether the id is taken in any tenant (to answer a clash without revealing that row)."""
        ...

    async def lock_id(self, group_id: uuid.UUID) -> None:
        """Serializes creates with the same client id until the transaction ends."""
        ...

    async def lock_existing(self, tenant_id: uuid.UUID, group_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
        """The given groups that exist in the tenant, kept from being deleted until the transaction ends."""
        ...

    async def update(self, group: ModifierGroup) -> None:
        """Rewrites the group and its options (options not listed any more are deleted)."""
        ...

    async def delete(self, tenant_id: uuid.UUID, group_id: uuid.UUID) -> None:
        """Deletes the group and detaches it from every item."""
        ...

    # Last on purpose: a method named `list` shadows the builtin in the annotations below it.
    async def list(self, tenant_id: uuid.UUID) -> list[ModifierGroup]:
        """Groups of the tenant by name (case-insensitive), each with its options in order."""
        ...
