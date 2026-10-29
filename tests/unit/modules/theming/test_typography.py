import uuid
from typing import Any

import pytest

from app.modules.theming.domain.theme import (
    FONT_ROLES,
    FONTS,
    TEXT_ELEMENTS,
    InvalidTheme,
    default_theme,
    parse_theme,
)

TENANT = uuid.uuid4()


def document(**changes: Any) -> dict[str, Any]:
    """The default theme as JSON, with `section__sub__field` overrides."""
    doc = default_theme().to_dict()
    for path, value in changes.items():
        target = doc
        *parents, leaf = path.split("__")
        for key in parents:
            target = target[key]
        target[leaf] = value
    return doc


def rejected_field(**changes: Any) -> str:
    with pytest.raises(InvalidTheme) as error:
        parse_theme(document(**changes), TENANT)
    return error.value.field


def test_the_curated_list_has_the_chosen_fonts_with_their_real_weights() -> None:
    assert set(FONTS) == {
        "geist", "inter", "poppins", "montserrat", "lato", "nunito", "playfair_display", "lora", "merriweather",
        "oswald", "bebas_neue", "pacifico", "caveat",
    }  # fmt: skip
    assert FONTS["playfair_display"].family == "Playfair Display"
    assert FONTS["bebas_neue"].weights == (400,) and not FONTS["bebas_neue"].italic
    assert FONTS["pacifico"].weights == (400,) and not FONTS["pacifico"].italic
    assert FONTS["lato"].weights == (100, 300, 400, 700, 900) and FONTS["lato"].italic
    assert FONTS["geist"].weights == (100, 200, 300, 400, 500, 600, 700, 800, 900) and not FONTS["geist"].italic


def test_the_default_typography_is_geist_with_the_current_menu_sizes() -> None:
    typography = default_theme().to_dict()["typography"]
    assert typography["scale"] == 100
    assert typography["fonts"] == {role: "geist" for role in FONT_ROLES} == {
        "heading": "geist", "body": "geist", "price": "geist", "button": "geist",
    }  # fmt: skip
    assert set(typography["elements"]) == set(TEXT_ELEMENTS) == {
        "business_name", "category", "product_name", "description", "price", "button",
    }  # fmt: skip
    name = typography["elements"]["business_name"]
    assert name == {
        "font": "heading", "size": 30, "weight": 600, "style": "normal", "line_height": 120,
        "letter_spacing": -25, "transform": "none", "align": "center",
    }  # fmt: skip
    assert typography["elements"]["description"]["size"] == 14
    assert typography["elements"]["price"]["font"] == "price"
    assert typography["elements"]["button"]["font"] == "button"
    assert parse_theme(default_theme().to_dict(), TENANT) == default_theme()


def test_each_element_can_have_its_own_font_and_settings() -> None:
    theme = parse_theme(
        document(
            typography__scale=120,
            typography__fonts__heading="playfair_display",
            typography__fonts__price="oswald",
            typography__elements__business_name={
                "font": "heading", "size": 48, "weight": 900, "style": "italic", "line_height": 110,
                "letter_spacing": 50, "transform": "uppercase", "align": "right",
            },  # fmt: skip
            typography__elements__price__font="price",
            typography__elements__price__weight=700,
        ),
        TENANT,
    )
    assert theme.typography.scale == 120
    assert theme.typography.fonts.heading == "playfair_display"
    name = theme.typography.elements.business_name
    assert (name.size, name.weight, name.style, name.transform, name.align) == (48, 900, "italic", "uppercase", "right")
    assert theme.typography.elements.price.weight == 700


@pytest.mark.parametrize(
    "font",
    ["comic_sans", "Playfair Display", "geist; } body { display:none", "https://evil.test/font.woff2", "", 3, None],
)
def test_a_font_outside_the_curated_list_is_rejected(font: Any) -> None:
    assert rejected_field(typography__fonts__heading=font) == "typography.fonts.heading"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("typography__scale", 79),
        ("typography__scale", 131),
        ("typography__scale", 1.0),
        ("typography__elements__category__size", 9),
        ("typography__elements__category__size", 73),
        ("typography__elements__category__size", "20px"),
        ("typography__elements__category__weight", 650),
        ("typography__elements__category__weight", 1000),
        ("typography__elements__category__weight", True),
        ("typography__elements__category__style", "oblique"),
        ("typography__elements__category__line_height", 99),
        ("typography__elements__category__line_height", 201),
        ("typography__elements__category__letter_spacing", -51),
        ("typography__elements__category__letter_spacing", 201),
        ("typography__elements__category__transform", "small-caps"),
        ("typography__elements__category__align", "justify"),
        ("typography__elements__category__font", "display"),
        ("typography__elements__category__font", "playfair_display"),
    ],
)
def test_out_of_range_numbers_and_unknown_choices_are_rejected(path: str, value: Any) -> None:
    assert rejected_field(**{path: value}) == path.replace("__", ".")


def test_a_weight_or_italic_the_elements_font_does_not_have_is_rejected() -> None:
    # Bebas Neue only has 400 and no italics; the price element uses the `price` role.
    assert (
        rejected_field(typography__fonts__price="bebas_neue", typography__elements__price__weight=600)
        == "typography.elements.price.weight"
    )
    assert (
        rejected_field(
            typography__fonts__price="bebas_neue",
            typography__elements__price__weight=400,
            typography__elements__price__style="italic",
        )
        == "typography.elements.price.style"
    )
    # Geist (the default) has no italics either.
    assert rejected_field(typography__elements__description__style="italic") == "typography.elements.description.style"
    # Lora has italics from 400 to 700.
    theme = parse_theme(
        document(
            typography__fonts__body="lora",
            typography__elements__description__style="italic",
            typography__elements__description__weight=400,
        ),
        TENANT,
    )
    assert theme.typography.elements.description.style == "italic"


def test_unknown_or_missing_typography_fields_are_rejected() -> None:
    extra = document()
    extra["typography"]["elements"]["price"]["css"] = "color:red"
    with pytest.raises(InvalidTheme, match=r"typography\.elements\.price\.css"):
        parse_theme(extra, TENANT)

    unknown_element = document()
    unknown_element["typography"]["elements"]["footer"] = unknown_element["typography"]["elements"]["price"]
    with pytest.raises(InvalidTheme, match=r"typography\.elements\.footer"):
        parse_theme(unknown_element, TENANT)

    missing = document()
    del missing["typography"]["fonts"]["button"]
    with pytest.raises(InvalidTheme, match=r"typography\.fonts\.button"):
        parse_theme(missing, TENANT)

    no_typography = document()
    del no_typography["typography"]
    with pytest.raises(InvalidTheme, match="typography"):
        parse_theme(no_typography, TENANT)

