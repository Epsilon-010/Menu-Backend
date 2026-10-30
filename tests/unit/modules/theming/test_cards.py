import uuid
from typing import Any

import pytest

from app.modules.theming.domain.theme import (
    ADD_BUTTON_SHAPES,
    ADD_BUTTON_STYLES,
    BADGE_SHAPES,
    BORDER_COLORS,
    BORDER_WIDTHS,
    CARD_ANIMATIONS,
    CARD_HOVERS,
    CARD_PADDINGS,
    CARD_RADII,
    CARD_SHADOWS,
    CARD_TEMPLATES,
    IMAGE_ASPECTS,
    IMAGE_FITS,
    IMAGE_POSITIONS,
    PRICE_POSITIONS,
    SCHEMA_VERSION,
    InvalidTheme,
    default_theme,
    parse_theme,
)

TENANT = uuid.uuid4()

DEFAULT_CARDS = {
    "template": "vertical",
    "image": {"aspect": "landscape", "fit": "cover", "position": "left"},
    "radius": "xl",
    "shadow": "none",
    "border": {"width": "thin", "color": "border"},
    "padding": "comfortable",
    "description_lines": 3,
    "price_position": "top",
    "add_button": {"style": "both", "shape": "rounded"},
    "hover": "none",
    "animation": "none",
    "overlay_opacity": 60,
    "badge_shape": "pill",
}


def document(**cards: Any) -> dict[str, Any]:
    doc = default_theme().to_dict()
    doc["cards"].update(cards)
    return doc


def rejected_field(doc: dict[str, Any]) -> str:
    with pytest.raises(InvalidTheme) as error:
        parse_theme(doc, TENANT)
    return error.value.field


def test_the_theme_is_version_4_and_the_default_cards_are_the_current_card() -> None:
    assert SCHEMA_VERSION == 4
    doc = default_theme().to_dict()
    assert doc["schema_version"] == 4
    assert doc["cards"] == DEFAULT_CARDS
    assert parse_theme(doc, TENANT) == default_theme()


def test_the_card_choices_are_the_ones_the_admin_can_pick() -> None:
    assert CARD_TEMPLATES == ("vertical", "horizontal", "overlay")
    assert IMAGE_ASPECTS == ("square", "landscape", "wide")
    assert IMAGE_FITS == ("cover", "contain")
    assert IMAGE_POSITIONS == ("left", "right")
    assert CARD_RADII == ("none", "sm", "md", "lg", "xl")
    assert CARD_SHADOWS == ("none", "sm", "md", "lg")
    assert BORDER_WIDTHS == ("none", "thin", "thick")
    assert BORDER_COLORS == ("border", "primary", "accent")
    assert CARD_PADDINGS == ("compact", "comfortable", "spacious")
    assert PRICE_POSITIONS == ("top", "bottom")
    assert ADD_BUTTON_STYLES == ("text", "icon", "both")
    assert ADD_BUTTON_SHAPES == ("square", "rounded", "pill")
    assert CARD_HOVERS == ("none", "lift", "grow")
    assert CARD_ANIMATIONS == ("none", "fade", "rise")
    assert BADGE_SHAPES == ("pill", "rounded")


@pytest.mark.parametrize("template", ["vertical", "horizontal", "overlay"])
def test_every_template_is_accepted(template: str) -> None:
    assert parse_theme(document(template=template), TENANT).cards.template == template


def test_every_option_is_kept_as_given() -> None:
    given = {
        "template": "overlay",
        "image": {"aspect": "wide", "fit": "contain", "position": "right"},
        "radius": "none",
        "shadow": "lg",
        "border": {"width": "thick", "color": "accent"},
        "padding": "spacious",
        "description_lines": 0,
        "price_position": "bottom",
        "add_button": {"style": "icon", "shape": "pill"},
        "hover": "lift",
        "animation": "rise",
        "overlay_opacity": 90,
        "badge_shape": "rounded",
    }
    assert parse_theme(document(**given), TENANT).to_dict()["cards"] == given


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"template": "minimal"}, "cards.template"),
        ({"template": "Vertical"}, "cards.template"),
        ({"image": {"aspect": "3:2", "fit": "cover", "position": "left"}}, "cards.image.aspect"),
        ({"image": {"aspect": "square", "fit": "fill", "position": "left"}}, "cards.image.fit"),
        ({"image": {"aspect": "square", "fit": "cover", "position": "top"}}, "cards.image.position"),
        ({"image": {"aspect": "square", "fit": "cover"}}, "cards.image.position"),
        ({"image": {"aspect": "square", "fit": "cover", "position": "left", "url": "x"}}, "cards.image.url"),
        ({"radius": "2xl"}, "cards.radius"),
        ({"shadow": "0 0 8px red"}, "cards.shadow"),
        ({"border": {"width": "3px", "color": "border"}}, "cards.border.width"),
        ({"border": {"width": "thin", "color": "#ff0000"}}, "cards.border.color"),
        ({"padding": 16}, "cards.padding"),
        ({"description_lines": -1}, "cards.description_lines"),
        ({"description_lines": 7}, "cards.description_lines"),
        ({"description_lines": 2.0}, "cards.description_lines"),
        ({"description_lines": True}, "cards.description_lines"),
        ({"price_position": "left"}, "cards.price_position"),
        ({"add_button": {"style": "emoji", "shape": "rounded"}}, "cards.add_button.style"),
        ({"add_button": {"style": "both", "shape": "circle"}}, "cards.add_button.shape"),
        ({"hover": "spin"}, "cards.hover"),
        ({"animation": "<style>"}, "cards.animation"),
        ({"overlay_opacity": 29}, "cards.overlay_opacity"),
        ({"overlay_opacity": 91}, "cards.overlay_opacity"),
        ({"overlay_opacity": "60"}, "cards.overlay_opacity"),
        ({"badge_shape": "star"}, "cards.badge_shape"),
    ],
)
def test_out_of_range_values_and_unknown_choices_are_rejected(change: dict[str, Any], field: str) -> None:
    assert rejected_field(document(**change)) == field


def test_missing_or_unknown_card_fields_are_rejected() -> None:
    doc = document()
    del doc["cards"]["hover"]
    assert rejected_field(doc) == "cards.hover"

    assert rejected_field(document(css="body{}")) == "cards.css"

    doc = document()
    del doc["cards"]
    assert rejected_field(doc) == "cards"


def test_a_version_3_document_is_no_longer_accepted() -> None:
    doc = default_theme().to_dict()
    del doc["cards"]
    doc["schema_version"] = 3
    assert rejected_field(doc) == "schema_version"
