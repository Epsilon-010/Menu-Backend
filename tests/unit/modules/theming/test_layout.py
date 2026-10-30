import uuid
from typing import Any

import pytest

from app.modules.theming.domain.theme import (
    CART_STYLES,
    CATEGORY_HEADERS,
    DENSITIES,
    NAVIGATIONS,
    PRODUCT_VIEWS,
    InvalidTheme,
    default_theme,
    parse_theme,
)

TENANT = uuid.uuid4()


def document(**layout: Any) -> dict[str, Any]:
    doc = default_theme().to_dict()
    doc["layout"].update(layout)
    return doc


def rejected_field(doc: dict[str, Any]) -> str:
    with pytest.raises(InvalidTheme) as error:
        parse_theme(doc, TENANT)
    return error.value.field


def test_the_default_layout_is_the_current_menu() -> None:
    doc = default_theme().to_dict()
    assert doc["layout"] == {
        "navigation": "chips",
        "product_view": "grid",
        "columns": 2,
        "density": "comfortable",
        "sticky_header": True,
        "category_header": "plain",
        "show_banner": True,
        "show_tagline": True,
        "show_welcome": True,
        "cart": "bar",
    }
    assert parse_theme(doc, TENANT) == default_theme()


def test_the_layout_choices_are_the_ones_the_admin_can_pick() -> None:
    assert NAVIGATIONS == ("chips", "tabs", "sidebar", "sections")
    assert PRODUCT_VIEWS == ("grid", "list", "carousel")
    assert DENSITIES == ("compact", "comfortable", "spacious")
    assert CATEGORY_HEADERS == ("plain", "underline", "band")
    assert CART_STYLES == ("bar", "panel", "floating")


@pytest.mark.parametrize("navigation", ["chips", "tabs", "sidebar", "sections"])
@pytest.mark.parametrize("view", ["grid", "list", "carousel"])
def test_every_navigation_and_product_view_is_accepted(navigation: str, view: str) -> None:
    layout = parse_theme(document(navigation=navigation, product_view=view), TENANT).layout
    assert (layout.navigation, layout.product_view) == (navigation, view)


def test_every_other_option_is_kept_as_given() -> None:
    given = {
        "columns": 4,
        "density": "spacious",
        "sticky_header": False,
        "category_header": "band",
        "show_banner": False,
        "show_tagline": False,
        "show_welcome": False,
        "cart": "floating",
    }
    assert {key: value for key, value in parse_theme(document(**given), TENANT).to_dict()["layout"].items() if key in given} == given


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("navigation", "dropdown"),
        ("navigation", "Chips"),
        ("product_view", "masonry"),
        ("columns", 0),
        ("columns", 5),
        ("columns", 2.0),
        ("columns", True),
        ("columns", "2"),
        ("density", "tight"),
        ("sticky_header", 1),
        ("sticky_header", "true"),
        ("category_header", "image"),
        ("show_banner", None),
        ("show_tagline", 0),
        ("show_welcome", "yes"),
        ("cart", "drawer"),
        ("cart", "<style>"),
    ],
)
def test_out_of_range_values_and_unknown_choices_are_rejected(field: str, value: Any) -> None:
    assert rejected_field(document(**{field: value})) == f"layout.{field}"


def test_missing_or_unknown_layout_fields_are_rejected() -> None:
    doc = document()
    del doc["layout"]["cart"]
    assert rejected_field(doc) == "layout.cart"

    assert rejected_field(document(css="body{}")) == "layout.css"

    doc = document()
    del doc["layout"]
    assert rejected_field(doc) == "layout"


def test_a_version_2_document_is_no_longer_accepted() -> None:
    doc = default_theme().to_dict()
    del doc["layout"]
    del doc["cards"]
    doc["schema_version"] = 2
    assert rejected_field(doc) == "schema_version"
