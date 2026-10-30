"""The options a table picks for a dish, checked against the item's modifier groups as the menu has them now."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.modules.orders.domain.errors import InvalidOrderData, ItemsUnavailable

# The most options a dish can carry: 10 groups of up to 30 options (the catalog limits).
MAX_CHOSEN_OPTIONS = 300


@dataclass(frozen=True)
class MenuModifierOption:
    option_id: uuid.UUID
    name: str
    price_cents: int
    available: bool = True


@dataclass(frozen=True)
class MenuModifierGroup:
    group_id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    options: tuple[MenuModifierOption, ...]


@dataclass(frozen=True)
class ChosenModifier:
    """One picked option; sent orders keep a copy, so later menu changes never alter them."""

    option_id: uuid.UUID
    group: str
    name: str
    price_cents: int


class Orderable(Protocol):
    """A menu item as the selection rules need it (the ports' MenuItem)."""

    @property
    def item_id(self) -> uuid.UUID: ...

    @property
    def price_cents(self) -> int: ...

    @property
    def modifier_groups(self) -> tuple[MenuModifierGroup, ...]: ...


def _rule(group: MenuModifierGroup) -> str:
    def options(count: int) -> str:
        return "option" if count == 1 else "options"

    if group.min_select == group.max_select:
        return f"Choose {group.max_select} {options(group.max_select)} for {group.name}"
    if group.min_select == 0:
        return f"Choose up to {group.max_select} {options(group.max_select)} for {group.name}"
    return f"Choose between {group.min_select} and {group.max_select} options for {group.name}"


def validate_option_ids(option_ids: Iterable[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    """Checked before anything else (a repeated add included): each option at most once."""
    requested = tuple(option_ids)
    if len(requested) != len(set(requested)):
        raise InvalidOrderData("Each option can be chosen once")
    return requested


def known_modifiers(item: Orderable, option_ids: Iterable[uuid.UUID]) -> tuple[ChosenModifier, ...]:
    """The options of the selection that still exist on the item, without checking any rule: what a line
    that can no longer be ordered as it is still shows, so the table can fix it."""
    wanted = set(option_ids)
    return tuple(
        ChosenModifier(option_id=option.option_id, group=group.name, name=option.name, price_cents=option.price_cents)
        for group in item.modifier_groups
        for option in group.options
        if option.option_id in wanted
    )


def choose_modifiers(item: Orderable, option_ids: Iterable[uuid.UUID]) -> tuple[ChosenModifier, ...]:
    """The selection in the item's group order, then option order.

    Raises InvalidOrderData when it breaks a rule (422) and ItemsUnavailable when it picks a sold-out
    option (409, like an item that left the menu).
    """
    requested = validate_option_ids(option_ids)
    known = {option.option_id for group in item.modifier_groups for option in group.options}
    if not set(requested) <= known:
        raise InvalidOrderData("Unknown option")
    chosen: list[ChosenModifier] = []
    for group in item.modifier_groups:
        picked = [option for option in group.options if option.option_id in requested]
        if not group.min_select <= len(picked) <= group.max_select:
            raise InvalidOrderData(_rule(group))
        if not all(option.available for option in picked):
            raise ItemsUnavailable([item.item_id])
        chosen.extend(
            ChosenModifier(option_id=option.option_id, group=group.name, name=option.name, price_cents=option.price_cents)
            for option in picked
        )
    return tuple(chosen)


def unit_price(item: Orderable, chosen: Iterable[ChosenModifier]) -> int:
    return item.price_cents + sum(modifier.price_cents for modifier in chosen)
