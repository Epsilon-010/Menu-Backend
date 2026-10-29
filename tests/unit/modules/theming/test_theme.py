import copy
import uuid
from typing import Any

import pytest

from app.modules.theming.domain.theme import (
    BACKGROUND_PATTERNS,
    SCHEMA_VERSION,
    InvalidTheme,
    contrast_ratio,
    contrast_warnings,
    default_colors,
    default_theme,
    parse_theme,
)
from app.shared.domain.images import ImageKind, new_image_public_id

TENANT = uuid.uuid4()


def document(**changes: Any) -> dict[str, Any]:
    """The default theme as JSON, with `section.field` (or `section.sub.field`) overrides."""
    doc = default_theme().to_dict()
    for path, value in changes.items():
        target = doc
        *parents, leaf = path.split("__")
        for key in parents:
            target = target[key]
        target[leaf] = value
    return doc


def test_the_default_theme_is_complete_and_valid() -> None:
    doc = default_theme().to_dict()
    assert doc["schema_version"] == SCHEMA_VERSION == 3
    assert doc["colors"]["mode"] == "light"
    assert parse_theme(doc, TENANT).to_dict() == doc
    assert set(doc["colors"]) == {
        "mode", "primary", "secondary", "accent", "background", "surface", "text", "text_muted", "price",
        "button_bg", "button_text", "button_hover", "border", "badge_bg", "badge_text", "cart_bg", "cart_text",
        "gradient",
    }  # fmt: skip
    assert set(doc["brand"]) == {"name", "tagline", "welcome_message", "logo", "banner", "background"}
    assert doc["brand"]["name"] == ""  # empty: the menu shows the tenant's name


def test_each_mode_has_its_own_default_palette() -> None:
    light, dark = default_colors("light"), default_colors("dark")
    assert light.mode == "light" and dark.mode == "dark"
    assert light.background != dark.background
    assert contrast_warnings(light) == [] and contrast_warnings(dark) == []


@pytest.mark.parametrize(
    ("given", "stored"),
    [("#1A2B3C", "#1a2b3c"), ("#abc", "#aabbcc"), ("rgb(255, 0, 16)", "#ff0010"), (" rgb(1,2,3) ", "#010203")],
)
def test_colors_accept_hex_and_rgb_and_are_stored_as_hex(given: str, stored: str) -> None:
    assert parse_theme(document(colors__primary=given), TENANT).colors.primary == stored


@pytest.mark.parametrize(
    "value",
    [
        "red",
        "#12345",
        "#gggggg",
        "rgb(256, 0, 0)",
        "#fff; background: url(https://evil.test/x.png)",
        "red;}</style><script>alert(1)</script>",
        "url(javascript:alert(1))",
        "var(--x)",
        "expression(alert(1))",
        "",
        12,
        None,
    ],
)
def test_a_malformed_or_injected_color_is_rejected(value: Any) -> None:
    with pytest.raises(InvalidTheme) as error:
        parse_theme(document(colors__primary=value), TENANT)
    assert str(error.value) == "Invalid theme value: colors.primary"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("colors__mode", "sepia"),
        ("colors__gradient__angle", 361),
        ("colors__gradient__angle", 10.5),
        ("colors__gradient__enabled", "yes"),
        ("brand__logo__size", "xl"),
        ("brand__logo__position", "right"),
        ("brand__banner__overlay_opacity", 101),
        ("brand__banner__overlay_opacity", True),
        ("brand__background__kind", "video"),
        ("brand__background__pattern", "<svg onload=alert(1)>"),
        ("brand__background__blur", 21),
        ("brand__background__opacity", -1),
        ("brand__name", "x" * 61),
        ("brand__tagline", "x" * 121),
        ("brand__welcome_message", "x" * 281),
        ("brand__name", "Tacos\x07"),
    ],
)
def test_out_of_range_values_and_unknown_choices_are_rejected(path: str, value: Any) -> None:
    with pytest.raises(InvalidTheme) as error:
        parse_theme(document(**{path: value}), TENANT)
    assert str(error.value) == f"Invalid theme value: {path.replace('__', '.')}"


def test_unknown_or_missing_fields_and_other_versions_are_rejected() -> None:
    extra = document()
    extra["colors"]["css"] = "body{display:none}"
    with pytest.raises(InvalidTheme, match=r"colors\.css"):
        parse_theme(extra, TENANT)

    missing = document()
    del missing["brand"]["tagline"]
    with pytest.raises(InvalidTheme, match=r"brand\.tagline"):
        parse_theme(missing, TENANT)

    for version in (1, 2, 4, True):
        with pytest.raises(InvalidTheme, match="schema_version"):
            parse_theme(document(schema_version=version), TENANT)


def test_texts_are_trimmed_and_the_welcome_message_keeps_line_breaks() -> None:
    theme = parse_theme(
        document(brand__name="  Tacos  ", brand__tagline=" Since 1990 ", brand__welcome_message="Hi!\nWelcome"),
        TENANT,
    )
    assert (theme.brand.name, theme.brand.tagline, theme.brand.welcome_message) == ("Tacos", "Since 1990", "Hi!\nWelcome")


def test_images_must_be_public_ids_of_this_tenant_for_that_slot() -> None:
    logo = new_image_public_id(TENANT, ImageKind.LOGO)
    banner = new_image_public_id(TENANT, ImageKind.BANNER)
    background = new_image_public_id(TENANT, ImageKind.BACKGROUND)
    theme = parse_theme(
        document(
            brand__logo__image_id=logo,
            brand__banner__image_id=banner,
            brand__background__kind="image",
            brand__background__image_id=background,
        ),
        TENANT,
    )
    assert theme.image_ids() == {logo, banner, background}

    for path, value in [
        ("brand__logo__image_id", banner),  # another slot's folder
        ("brand__logo__image_id", new_image_public_id(uuid.uuid4(), ImageKind.LOGO)),  # another tenant
        ("brand__banner__image_id", "https://evil.test/banner.png"),
        ("brand__banner__image_id", new_image_public_id(TENANT, ImageKind.ITEM)),
    ]:
        with pytest.raises(InvalidTheme, match=path.replace("__", r"\.")):
            parse_theme(document(**{path: value}), TENANT)


def test_an_image_background_needs_an_image_and_patterns_come_from_the_list() -> None:
    with pytest.raises(InvalidTheme, match=r"brand\.background\.image_id"):
        parse_theme(document(brand__background__kind="image"), TENANT)
    for pattern in BACKGROUND_PATTERNS:
        parsed = parse_theme(document(brand__background__kind="pattern", brand__background__pattern=pattern), TENANT)
        assert parsed.brand.background.pattern == pattern


def test_parsing_never_changes_the_given_document() -> None:
    doc = document(colors__primary="#ABC")
    before = copy.deepcopy(doc)
    parse_theme(doc, TENANT)
    assert doc == before


def test_contrast_follows_wcag() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)


def test_low_contrast_pairs_are_reported_as_warnings_not_errors() -> None:
    theme = parse_theme(document(colors__button_text="#eeeeee", colors__button_bg="#ffffff"), TENANT)
    warnings = contrast_warnings(theme.colors)
    assert [(w.foreground, w.background) for w in warnings] == [("button_text", "button_bg")]
    assert warnings[0].ratio < 4.5
