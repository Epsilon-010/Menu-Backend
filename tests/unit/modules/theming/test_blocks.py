"""UX round 2 (S4, S6): draggable card and header blocks, and a product view per category (schema_version 5)."""

import uuid
from typing import Any

import pytest

from app.modules.theming.domain.presets import PRESETS
from app.modules.theming.domain.theme import (
    CARD_BLOCKS,
    HEADER_BLOCKS,
    MAX_CATEGORY_LAYOUTS,
    SCHEMA_VERSION,
    CategoryLayout,
    InvalidTheme,
    default_theme,
    parse_theme,
)

TENANT = uuid.uuid4()
CATEGORY = "0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f87"

Json = dict[str, Any]


def document() -> Json:
    return default_theme().to_dict()


def rejected_field(doc: Json) -> str:
    with pytest.raises(InvalidTheme) as error:
        parse_theme(doc, TENANT)
    return error.value.field


def entry(product_view: str = "list", columns: int = 1, card_template: str = "horizontal") -> Json:
    return {"product_view": product_view, "columns": columns, "card_template": card_template}


def test_the_theme_is_version_5_and_the_defaults_keep_the_current_menu() -> None:
    assert SCHEMA_VERSION == 6
    doc = document()
    assert doc["schema_version"] == 6
    assert doc["cards"]["blocks"] == ["image", "badges", "heading", "description", "add_button"]
    assert doc["layout"]["header_blocks"] == ["banner", "name", "tagline", "welcome"]
    assert doc["layout"]["categories"] == {}
    assert parse_theme(doc, TENANT) == default_theme()
    assert parse_theme(doc, TENANT).to_dict() == doc


def test_the_blocks_are_the_ones_the_admin_can_drag() -> None:
    assert CARD_BLOCKS == ("image", "badges", "heading", "description", "add_button")
    assert HEADER_BLOCKS == ("banner", "name", "tagline", "welcome")
    assert MAX_CATEGORY_LAYOUTS == 100


def test_any_order_of_the_blocks_is_kept() -> None:
    doc = document()
    doc["cards"]["blocks"] = ["add_button", "badges", "description", "heading", "image"]
    doc["layout"]["header_blocks"] = ["welcome", "tagline", "name", "banner"]
    theme = parse_theme(doc, TENANT)
    assert theme.cards.blocks == ("add_button", "badges", "description", "heading", "image")
    assert theme.layout.header_blocks == ("welcome", "tagline", "name", "banner")
    assert theme.to_dict() == doc


@pytest.mark.parametrize(
    "blocks",
    [
        ["image", "heading", "description", "badges"],  # one missing
        ["image", "heading", "description", "badges", "add_button", "image"],  # repeated
        ["image", "heading", "description", "badges", "badges"],  # repeated instead of one
        ["image", "heading", "description", "badges", "price"],  # unknown
        [],
        "image,heading,description,badges,add_button",
        None,
        ["image", "heading", "description", "badges", 4],
    ],
)
def test_the_card_blocks_must_be_exactly_the_five_blocks(blocks: Any) -> None:
    doc = document()
    doc["cards"]["blocks"] = blocks
    assert rejected_field(doc) == "cards.blocks"


@pytest.mark.parametrize(
    "blocks",
    [
        ["banner", "name", "tagline"],
        ["banner", "name", "tagline", "welcome", "logo"],
        ["banner", "name", "name", "welcome"],
        {"banner": 1},
    ],
)
def test_the_header_blocks_must_be_exactly_the_four_blocks(blocks: Any) -> None:
    doc = document()
    doc["layout"]["header_blocks"] = blocks
    assert rejected_field(doc) == "layout.header_blocks"


@pytest.mark.parametrize("missing", ["blocks"])
def test_the_card_blocks_are_required(missing: str) -> None:
    doc = document()
    del doc["cards"][missing]
    assert rejected_field(doc) == "cards.blocks"


@pytest.mark.parametrize("missing", ["header_blocks", "categories"])
def test_the_header_blocks_and_categories_are_required(missing: str) -> None:
    doc = document()
    del doc["layout"][missing]
    assert rejected_field(doc) == f"layout.{missing}"


def test_a_category_gets_its_own_view_columns_and_template() -> None:
    doc = document()
    doc["layout"]["categories"] = {CATEGORY: entry("carousel", 3, "overlay")}
    theme = parse_theme(doc, TENANT)
    assert theme.layout.categories == {CATEGORY: CategoryLayout("carousel", 3, "overlay")}
    assert theme.to_dict()["layout"]["categories"] == {CATEGORY: entry("carousel", 3, "overlay")}


@pytest.mark.parametrize("view", ["grid", "list", "carousel"])
@pytest.mark.parametrize("template", ["vertical", "horizontal", "overlay"])
def test_every_view_and_template_is_accepted_for_a_category(view: str, template: str) -> None:
    doc = document()
    doc["layout"]["categories"] = {CATEGORY: entry(view, 4, template)}
    assert parse_theme(doc, TENANT).layout.categories[CATEGORY] == CategoryLayout(view, 4, template)


def test_an_uppercase_category_id_is_stored_lowercase() -> None:
    doc = document()
    doc["layout"]["categories"] = {CATEGORY.upper(): entry()}
    theme = parse_theme(doc, TENANT)
    assert list(theme.layout.categories) == [CATEGORY]
    assert list(theme.to_dict()["layout"]["categories"]) == [CATEGORY]


def test_the_same_category_written_twice_is_rejected() -> None:
    doc = document()
    doc["layout"]["categories"] = {CATEGORY: entry(), CATEGORY.upper(): entry("grid", 2, "vertical")}
    assert rejected_field(doc) == "layout.categories"


@pytest.mark.parametrize(
    "key",
    [
        "breakfast",
        "",
        "0b6f3c2e6a8d4f6e9a513d2c1b0a9f87",  # not the hyphenated form
        "{0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f87}",
        "urn:uuid:0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f87",
        " 0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f87",
        "0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f8g",
    ],
)
def test_a_category_key_that_is_not_a_uuid_is_rejected_without_echoing_it(key: str) -> None:
    doc = document()
    doc["layout"]["categories"] = {key: entry()}
    field = rejected_field(doc)
    assert field == "layout.categories"


def test_at_most_100_categories_are_kept() -> None:
    doc = document()
    doc["layout"]["categories"] = {str(uuid.uuid4()): entry() for _ in range(100)}
    assert len(parse_theme(doc, TENANT).layout.categories) == 100
    doc["layout"]["categories"][str(uuid.uuid4())] = entry()
    assert rejected_field(doc) == "layout.categories"


@pytest.mark.parametrize(
    ("value", "field"),
    [
        ({"product_view": "masonry", "columns": 1, "card_template": "vertical"}, "product_view"),
        ({"product_view": "grid", "columns": 0, "card_template": "vertical"}, "columns"),
        ({"product_view": "grid", "columns": 5, "card_template": "vertical"}, "columns"),
        ({"product_view": "grid", "columns": True, "card_template": "vertical"}, "columns"),
        ({"product_view": "grid", "columns": "2", "card_template": "vertical"}, "columns"),
        ({"product_view": "grid", "columns": 2, "card_template": "minimal"}, "card_template"),
        ({"columns": 2, "card_template": "vertical"}, "product_view"),
        ({"product_view": "grid", "card_template": "vertical"}, "columns"),
        ({"product_view": "grid", "columns": 2}, "card_template"),
        ({"product_view": "grid", "columns": 2, "card_template": "vertical", "density": "compact"}, "density"),
    ],
)
def test_each_category_needs_exactly_its_three_valid_values(value: Json, field: str) -> None:
    doc = document()
    doc["layout"]["categories"] = {CATEGORY: value}
    assert rejected_field(doc) == f"layout.categories.{CATEGORY}.{field}"


@pytest.mark.parametrize("categories", [[], "grid", None, 3])
def test_the_categories_must_be_an_object(categories: Any) -> None:
    doc = document()
    doc["layout"]["categories"] = categories
    assert rejected_field(doc) == "layout.categories"


@pytest.mark.parametrize("value", [None, [], "grid"])
def test_a_category_entry_must_be_an_object(value: Any) -> None:
    doc = document()
    doc["layout"]["categories"] = {CATEGORY: value}
    assert rejected_field(doc) == f"layout.categories.{CATEGORY}"


def test_every_preset_starts_from_the_default_blocks_and_no_category_overrides() -> None:
    defaults = default_theme()
    for preset in PRESETS:
        assert preset.cards.blocks == defaults.cards.blocks
        assert preset.layout.header_blocks == defaults.layout.header_blocks
        assert preset.layout.categories == {}
        doc = preset.to_dict()
        assert doc["cards"]["blocks"] == list(CARD_BLOCKS)
        assert doc["layout"]["header_blocks"] == list(HEADER_BLOCKS)
        assert doc["layout"]["categories"] == {}
