import uuid

import pytest

from app.modules.orders.domain.errors import InvalidOrderData, ItemsUnavailable
from app.modules.orders.domain.modifiers import (
    ChosenModifier,
    MenuModifierGroup,
    MenuModifierOption,
    choose_modifiers,
    unit_price,
)
from app.modules.orders.domain.ports import MenuItem


def option(name: str, price_cents: int = 0, available: bool = True) -> MenuModifierOption:
    return MenuModifierOption(option_id=uuid.uuid4(), name=name, price_cents=price_cents, available=available)


SMALL, LARGE = option("Small"), option("Large", 1500)
CHEESE, AVOCADO, BEANS, ONION = option("Cheese", 500), option("Avocado", 900), option("Beans"), option("Onion")
SIZE = MenuModifierGroup(group_id=uuid.uuid4(), name="Size", min_select=1, max_select=1, options=(SMALL, LARGE))
EXTRAS = MenuModifierGroup(
    group_id=uuid.uuid4(), name="Extras", min_select=0, max_select=3, options=(CHEESE, AVOCADO, BEANS, ONION)
)
TACO = MenuItem(item_id=uuid.uuid4(), name="Taco", price_cents=2500, modifier_groups=(SIZE, EXTRAS))


def test_a_valid_selection_lists_the_options_in_group_and_option_order() -> None:
    chosen = choose_modifiers(TACO, [AVOCADO.option_id, LARGE.option_id, CHEESE.option_id])

    assert chosen == (
        ChosenModifier(option_id=LARGE.option_id, group="Size", name="Large", price_cents=1500),
        ChosenModifier(option_id=CHEESE.option_id, group="Extras", name="Cheese", price_cents=500),
        ChosenModifier(option_id=AVOCADO.option_id, group="Extras", name="Avocado", price_cents=900),
    )
    assert unit_price(TACO, chosen) == 2500 + 1500 + 500 + 900


def test_an_item_without_groups_takes_no_options() -> None:
    plain = MenuItem(item_id=uuid.uuid4(), name="Agua", price_cents=1000)

    assert choose_modifiers(plain, []) == ()
    with pytest.raises(InvalidOrderData, match="Unknown option"):
        choose_modifiers(plain, [SMALL.option_id])


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        ([], "Choose 1 option for Size"),
        ([SMALL.option_id, LARGE.option_id], "Choose 1 option for Size"),
        (
            [SMALL.option_id, CHEESE.option_id, AVOCADO.option_id, BEANS.option_id, ONION.option_id],
            "Choose up to 3 options for Extras",
        ),
    ],
)
def test_each_group_needs_between_its_min_and_max(selection: list[uuid.UUID], message: str) -> None:
    with pytest.raises(InvalidOrderData, match=message):
        choose_modifiers(TACO, selection)


def test_a_range_names_both_limits() -> None:
    sauces = MenuModifierGroup(
        group_id=uuid.uuid4(), name="Salsas", min_select=1, max_select=2, options=(CHEESE, AVOCADO, BEANS)
    )
    item = MenuItem(item_id=uuid.uuid4(), name="Taco", price_cents=2500, modifier_groups=(sauces,))

    with pytest.raises(InvalidOrderData, match="Choose between 1 and 2 options for Salsas"):
        choose_modifiers(item, [])


def test_each_option_can_be_chosen_once() -> None:
    with pytest.raises(InvalidOrderData, match="Each option can be chosen once"):
        choose_modifiers(TACO, [SMALL.option_id, CHEESE.option_id, CHEESE.option_id])


def test_an_option_of_another_item_is_unknown() -> None:
    with pytest.raises(InvalidOrderData, match="Unknown option"):
        choose_modifiers(TACO, [SMALL.option_id, uuid.uuid4()])


def test_a_sold_out_option_makes_the_item_unavailable() -> None:
    sold_out = option("Large", 1500, available=False)
    size = MenuModifierGroup(group_id=uuid.uuid4(), name="Size", min_select=1, max_select=1, options=(SMALL, sold_out))
    item = MenuItem(item_id=uuid.uuid4(), name="Taco", price_cents=2500, modifier_groups=(size,))

    with pytest.raises(ItemsUnavailable) as raised:
        choose_modifiers(item, [sold_out.option_id])
    assert raised.value.args[0] == [item.item_id]
