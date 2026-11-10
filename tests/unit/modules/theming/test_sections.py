"""Menu sections (S3, S5): the menu page as an ordered list of sections (schema_version 6)."""

import uuid
from typing import Any

import pytest

from app.modules.theming.domain.import_theme import import_theme
from app.modules.theming.domain.presets import PRESETS
from app.modules.theming.domain.theme import (
    DEFAULT_SECTIONS,
    MAX_FEATURED_ITEMS,
    MAX_SECTIONS,
    SCHEMA_VERSION,
    SECTION_TYPES,
    FeaturedSection,
    InvalidTheme,
    TextSection,
    default_theme,
    parse_theme,
)

TENANT = uuid.uuid4()
HERO_ID = "00000000-0000-4000-8000-000000000001"
MENU_ID = "00000000-0000-4000-8000-000000000002"
ITEM = "0b6f3c2e-6a8d-4f6e-9a51-3d2c1b0a9f87"

Json = dict[str, Any]


def document() -> Json:
    return default_theme().to_dict()


def with_sections(*sections: Json) -> Json:
    doc = document()
    doc["layout"]["sections"] = list(sections)
    return doc


def rejected_field(doc: Json) -> str:
    with pytest.raises(InvalidTheme) as error:
        parse_theme(doc, TENANT)
    return error.value.field


def new_id() -> str:
    return str(uuid.uuid4())


def hero() -> Json:
    return {"id": HERO_ID, "type": "hero"}


def menu() -> Json:
    return {"id": MENU_ID, "type": "menu"}


def featured(**changes: Any) -> Json:
    return {"id": new_id(), "type": "featured", "title": "Lo más pedido", "item_ids": [ITEM], "view": "carousel"} | changes


def text(**changes: Any) -> Json:
    section = {"id": new_id(), "type": "text", "title": "Promo", "body": "2x1 los martes", "align": "center"}
    return section | {"style": "highlight"} | changes


def test_the_theme_is_version_6_and_the_default_page_is_the_header_then_the_menu() -> None:
    assert SCHEMA_VERSION == 6
    assert SECTION_TYPES == ("hero", "menu", "featured", "text", "divider")
    assert (MAX_SECTIONS, MAX_FEATURED_ITEMS) == (20, 12)
    doc = document()
    assert doc["schema_version"] == 6
    assert doc["layout"]["sections"] == [hero(), menu()]
    assert parse_theme(doc, TENANT) == default_theme()
    assert parse_theme(doc, TENANT).to_dict() == doc
    assert default_theme().layout.sections == DEFAULT_SECTIONS


def test_every_kind_of_section_is_kept_in_the_order_given() -> None:
    sections = [text(), menu(), {"id": new_id(), "type": "divider"}, featured(view="grid"), hero()]
    doc = with_sections(*sections)
    theme = parse_theme(doc, TENANT)
    assert [section.type for section in theme.layout.sections] == ["text", "menu", "divider", "featured", "hero"]
    assert theme.to_dict() == doc
    assert isinstance(theme.layout.sections[0], TextSection)
    assert isinstance(theme.layout.sections[3], FeaturedSection)
    assert theme.layout.sections[3].item_ids == (ITEM,)


def test_the_page_can_be_just_the_menu_and_hold_repeated_sections() -> None:
    assert parse_theme(with_sections(menu()), TENANT).layout.sections[0].type == "menu"
    many = [featured() for _ in range(3)] + [text() for _ in range(3)] + [menu()]
    assert len(parse_theme(with_sections(*many), TENANT).layout.sections) == 7


def test_text_is_trimmed_and_ids_are_stored_lowercase() -> None:
    upper = new_id().upper()
    doc = with_sections(menu(), text(id=upper, title="  Promo  ", body=" línea 1\nlínea 2 "), featured(item_ids=[ITEM.upper()]))
    sections = parse_theme(doc, TENANT).layout.sections
    assert sections[1].id == upper.lower()
    assert (sections[1].title, sections[1].body) == ("Promo", "línea 1\nlínea 2")
    assert sections[2].item_ids == (ITEM,)


def test_featured_and_text_can_be_empty() -> None:
    doc = with_sections(menu(), featured(title="", item_ids=[]), text(title="", body=""))
    assert len(parse_theme(doc, TENANT).layout.sections) == 3


@pytest.mark.parametrize(
    ("sections", "field"),
    [
        ([], "layout.sections"),  # the menu is missing
        ([hero()], "layout.sections"),  # the menu is missing
        ([menu(), {"id": new_id(), "type": "menu"}], "layout.sections"),  # two menus
        ([menu(), hero(), {"id": new_id(), "type": "hero"}], "layout.sections"),  # two headers
        ([menu(), {"id": MENU_ID, "type": "divider"}], "layout.sections"),  # repeated id
        ([menu()] + [{"id": new_id(), "type": "divider"} for _ in range(20)], "layout.sections"),  # 21 sections
        ([menu(), {"id": new_id(), "type": "video"}], "layout.sections.1.type"),
        ([menu(), {"id": "not-a-uuid", "type": "divider"}], "layout.sections.1.id"),
        ([menu(), {"id": 7, "type": "divider"}], "layout.sections.1.id"),
        ([menu(), {"type": "divider"}], "layout.sections.1.id"),
        ([menu(), {"id": new_id(), "type": "divider", "title": "x"}], "layout.sections.1.title"),
        ([{"id": MENU_ID, "type": "menu", "view": "grid"}], "layout.sections.0.view"),
        ([menu(), "divider"], "layout.sections.1"),
        ([menu(), featured(view="list")], "layout.sections.1.view"),
        ([menu(), featured(title="x" * 61)], "layout.sections.1.title"),
        ([menu(), featured(item_ids=[ITEM, ITEM])], "layout.sections.1.item_ids"),
        ([menu(), featured(item_ids=[new_id() for _ in range(13)])], "layout.sections.1.item_ids"),
        ([menu(), featured(item_ids=["x"])], "layout.sections.1.item_ids"),
        ([menu(), featured(item_ids=ITEM)], "layout.sections.1.item_ids"),
        ([menu(), featured(title=None)], "layout.sections.1.title"),
        ([menu(), text(title="x" * 81)], "layout.sections.1.title"),
        ([menu(), text(body="x" * 501)], "layout.sections.1.body"),
        ([menu(), text(title="a\nb")], "layout.sections.1.title"),
        ([menu(), text(align="right")], "layout.sections.1.align"),
        ([menu(), text(style="loud")], "layout.sections.1.style"),
    ],
)
def test_invalid_sections_are_rejected_naming_the_field(sections: list[Any], field: str) -> None:
    assert rejected_field(with_sections(*sections)) == field


def test_sections_must_be_a_list() -> None:
    doc = document()
    doc["layout"]["sections"] = {"0": menu()}
    assert rejected_field(doc) == "layout.sections"
    del doc["layout"]["sections"]
    assert rejected_field(doc) == "layout.sections"


def test_every_template_defines_a_page_with_the_menu_and_no_products_of_its_own() -> None:
    for preset in PRESETS:
        types = [section.type for section in preset.layout.sections]
        assert types.count("menu") == 1, preset.id
        # A template is shared by every tenant: it never names one tenant's products.
        assert "featured" not in types, preset.id


def test_an_older_export_gets_the_default_page() -> None:
    doc = document()
    doc["schema_version"] = 5
    del doc["layout"]["sections"]
    imported = import_theme(doc, TENANT, available_images=set())
    assert imported.theme.schema_version == 6
    assert imported.theme.layout.sections == DEFAULT_SECTIONS


def test_a_version_5_export_that_already_has_sections_is_not_version_5() -> None:
    doc = document()
    doc["schema_version"] = 5
    with pytest.raises(InvalidTheme) as error:
        import_theme(doc, TENANT, available_images=set())
    assert error.value.field == "layout.sections"
