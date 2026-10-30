"""Slice 14: a theme document exported elsewhere (another tenant, an older version) brought into a draft."""

import copy
import uuid
from typing import Any

import pytest

from app.modules.theming.domain.import_theme import import_theme
from app.modules.theming.domain.theme import InvalidTheme, default_theme
from app.shared.domain.images import ImageKind, new_image_public_id

TENANT = uuid.uuid4()
OTHER = uuid.uuid4()

Json = dict[str, Any]


def current() -> Json:
    return default_theme().to_dict()


def older(version: int, **colors: str) -> Json:
    """A document as an earlier slice exported it: version 1 had no typography, 2 no layout, 3 no cards."""
    doc = current()
    for key in ("typography", "layout", "cards")[version - 1 :]:
        del doc[key]
    doc["schema_version"] = version
    doc["colors"].update(colors)
    return doc


def test_a_current_document_comes_back_as_it_is() -> None:
    doc = current()
    doc["colors"]["primary"] = "#123456"
    imported = import_theme(doc, TENANT, set())
    assert imported.theme.to_dict() == doc
    assert imported.removed_images == ()


@pytest.mark.parametrize("version", [1, 2, 3])
def test_an_older_version_gets_the_defaults_it_missed_and_keeps_the_rest(version: int) -> None:
    doc = older(version, primary="#123456")
    original = copy.deepcopy(doc)

    theme = import_theme(doc, TENANT, set()).theme.to_dict()

    assert doc == original  # the input is never changed
    assert theme["colors"]["primary"] == "#123456"
    assert theme == {**current(), "colors": theme["colors"]}


@pytest.mark.parametrize(("position", "align"), [("left", "left"), ("center", "center")])
def test_a_version_1_business_name_keeps_following_the_logo(position: str, align: str) -> None:
    doc = older(1)
    doc["brand"]["logo"]["position"] = position
    theme = import_theme(doc, TENANT, set()).theme
    assert theme.typography.elements.business_name.align == align


def test_the_upgrade_keeps_what_the_older_version_had() -> None:
    doc = older(3)
    doc["layout"]["navigation"] = "tabs"
    doc["typography"]["scale"] = 120
    theme = import_theme(doc, TENANT, set()).theme
    assert theme.layout.navigation == "tabs"
    assert theme.typography.scale == 120
    assert theme.cards == default_theme().cards


@pytest.mark.parametrize("version", [0, 5, 99, "4", 4.0, True, None])
def test_an_unknown_version_is_rejected(version: Any) -> None:
    doc = current()
    doc["schema_version"] = version
    with pytest.raises(InvalidTheme) as error:
        import_theme(doc, TENANT, set())
    assert error.value.field == "schema_version"


@pytest.mark.parametrize("raw", [None, [], "theme", 4, {}])
def test_something_that_is_not_a_theme_is_rejected(raw: Any) -> None:
    with pytest.raises(InvalidTheme):
        import_theme(raw, TENANT, set())


def test_an_older_version_with_a_bad_value_is_rejected_naming_the_field() -> None:
    doc = older(2)
    doc["colors"]["primary"] = "url(javascript:alert(1))"
    with pytest.raises(InvalidTheme) as error:
        import_theme(doc, TENANT, set())
    assert error.value.field == "colors.primary"
    assert "javascript" not in str(error.value)


def test_another_tenants_images_are_removed_and_named() -> None:
    doc = current()
    doc["brand"]["logo"]["image_id"] = new_image_public_id(OTHER, ImageKind.LOGO)
    doc["brand"]["banner"]["image_id"] = new_image_public_id(OTHER, ImageKind.BANNER)
    doc["brand"]["background"].update(kind="image", image_id=new_image_public_id(OTHER, ImageKind.BACKGROUND))
    doc["colors"]["primary"] = "#123456"

    imported = import_theme(doc, TENANT, set())

    assert imported.removed_images == ("logo", "banner", "background")
    brand = imported.theme.brand
    assert brand.logo.image_id is None and brand.banner.image_id is None and brand.background.image_id is None
    assert brand.background.kind == "none"  # a background image nobody can show is no background
    assert imported.theme.colors.primary == "#123456"


def test_own_images_stay_only_while_a_theme_of_the_tenant_still_uses_them() -> None:
    used = new_image_public_id(TENANT, ImageKind.LOGO)
    gone = new_image_public_id(TENANT, ImageKind.BANNER)
    doc = current()
    doc["brand"]["logo"]["image_id"] = used
    doc["brand"]["banner"]["image_id"] = gone
    doc["brand"]["background"].update(kind="pattern", image_id=None)

    imported = import_theme(doc, TENANT, {used})

    assert imported.theme.brand.logo.image_id == used
    assert imported.theme.brand.banner.image_id is None
    assert imported.theme.brand.background.kind == "pattern"
    assert imported.removed_images == ("banner",)


def test_an_image_id_that_is_not_text_is_rejected_not_removed() -> None:
    doc = current()
    doc["brand"]["logo"]["image_id"] = 42
    with pytest.raises(InvalidTheme) as error:
        import_theme(doc, TENANT, set())
    assert error.value.field == "brand.logo.image_id"


def test_a_document_nested_too_deep_is_rejected_not_a_crash() -> None:
    nested: Any = []
    for _ in range(5000):
        nested = [nested]
    doc = current()
    doc["evil"] = nested
    with pytest.raises(InvalidTheme) as error:
        import_theme(doc, TENANT, set())
    assert error.value.field == "theme"
