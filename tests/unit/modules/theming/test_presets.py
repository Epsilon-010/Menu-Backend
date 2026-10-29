import uuid
from dataclasses import replace

import pytest

from app.modules.theming.domain.presets import PRESETS, ThemePreset
from app.modules.theming.domain.theme import (
    FONTS,
    Logo,
    contrast_ratio,
    contrast_warnings,
    default_theme,
    parse_theme,
)
from app.shared.domain.images import ImageKind, new_image_public_id

TENANT = uuid.uuid4()

# Beyond the editor's warnings: the menu draws button text on the hover color too, category headings in the
# secondary color on the page, and muted text and prices on the page as well as on cards.
EXTRA_PAIRS = (
    ("button_text", "button_hover"),
    ("secondary", "background"),
    ("text_muted", "background"),
    ("price", "background"),
)


def ids(preset: ThemePreset) -> str:
    return preset.id


def test_there_are_several_presets_with_unique_ids_and_names() -> None:
    assert len(PRESETS) >= 6
    assert len({preset.id for preset in PRESETS}) == len(PRESETS)
    assert len({preset.name for preset in PRESETS}) == len(PRESETS)
    assert all(preset.name and preset.description for preset in PRESETS)


def test_the_first_preset_is_the_default_design() -> None:
    default = default_theme()
    assert PRESETS[0].colors == default.colors
    assert PRESETS[0].typography == default.typography


@pytest.mark.parametrize("preset", PRESETS, ids=ids)
def test_every_preset_is_a_valid_theme(preset: ThemePreset) -> None:
    doc = preset.apply(default_theme()).to_dict()
    assert parse_theme(doc, TENANT).to_dict() == doc


@pytest.mark.parametrize("preset", PRESETS, ids=ids)
def test_every_preset_is_readable(preset: ThemePreset) -> None:
    assert contrast_warnings(preset.colors) == []
    for foreground, background in EXTRA_PAIRS:
        ratio = contrast_ratio(getattr(preset.colors, foreground), getattr(preset.colors, background))
        assert ratio >= 4.5, f"{foreground} on {background}: {ratio:.2f}"


@pytest.mark.parametrize("preset", PRESETS, ids=ids)
def test_every_preset_mode_matches_its_background(preset: ThemePreset) -> None:
    on_white = contrast_ratio(preset.colors.background, "#ffffff")
    on_black = contrast_ratio(preset.colors.background, "#000000")
    assert (on_black > on_white) == (preset.colors.mode == "light")
    assert (on_black > on_white) == (contrast_ratio(preset.colors.surface, "#000000") > contrast_ratio(
        preset.colors.surface, "#ffffff"
    ))


@pytest.mark.parametrize("preset", PRESETS, ids=ids)
def test_every_preset_uses_fonts_from_the_curated_list(preset: ThemePreset) -> None:
    for role in ("heading", "body", "price", "button"):
        assert getattr(preset.typography.fonts, role) in FONTS


def test_both_modes_are_offered() -> None:
    assert {preset.colors.mode for preset in PRESETS} == {"light", "dark"}


def test_applying_a_preset_changes_colors_and_typography_but_keeps_the_brand() -> None:
    logo = new_image_public_id(TENANT, ImageKind.LOGO)
    default = default_theme()
    mine = replace(
        default,
        brand=replace(default.brand, name="Tacos El Primo", logo=Logo(image_id=logo, size="lg", position="left")),
    )
    preset = PRESETS[-1]

    applied = preset.apply(mine)

    assert applied.brand == mine.brand
    assert applied.colors == preset.colors
    assert applied.typography == preset.typography
    assert applied.schema_version == mine.schema_version
    assert applied.images() == {logo: ImageKind.LOGO}


def test_a_preset_as_json_names_colors_like_the_theme_document() -> None:
    doc = PRESETS[0].to_dict()
    theme = default_theme().to_dict()
    assert doc == {
        "id": PRESETS[0].id,
        "name": PRESETS[0].name,
        "description": PRESETS[0].description,
        "colors": theme["colors"],
        "typography": theme["typography"],
    }
