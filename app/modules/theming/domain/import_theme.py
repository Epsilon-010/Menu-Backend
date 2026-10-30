"""Bringing an exported theme document into a tenant's draft: older versions are upgraded, foreign images dropped.

The upgrade adds what each schema version introduced with the same frozen values as the data migrations that moved
the stored themes (3f7686d2fe3f typography, 9c2e41b7d5a3 layout, c5d18a7e4f20 cards), so an old export looks exactly
as a stored theme of that version looks today. Those values are copies on purpose: the app's defaults may change.
"""

import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.modules.theming.domain.theme import SCHEMA_VERSION, Theme, parse_theme

IMAGE_SLOTS = ("logo", "banner", "background")


def _text(font: str, size: int, weight: int, line_height: int, letter_spacing: int = 0, align: str = "left") -> dict[str, Any]:
    return {
        "font": font,
        "size": size,
        "weight": weight,
        "style": "normal",
        "line_height": line_height,
        "letter_spacing": letter_spacing,
        "transform": "none",
        "align": align,
    }


# Added by schema_version 2; the business name follows the logo position, as before typography existed.
_TYPOGRAPHY_V2 = {
    "scale": 100,
    "fonts": {"heading": "geist", "body": "geist", "price": "geist", "button": "geist"},
    "elements": {
        "business_name": _text("heading", 30, 600, 120, -25, align="center"),
        "category": _text("heading", 20, 600, 140, -25),
        "product_name": _text("heading", 16, 600, 150),
        "description": _text("body", 14, 400, 143),
        "price": _text("price", 16, 600, 150),
        "button": _text("button", 14, 600, 143),
    },
}

# Added by schema_version 3.
_LAYOUT_V3 = {
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

# Added by schema_version 4.
_CARDS_V4 = {
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


@dataclass(frozen=True)
class ImportedTheme:
    theme: Theme
    # Image slots emptied because the image is another tenant's or no theme of this tenant uses it anymore.
    removed_images: tuple[str, ...]


def _logo_position(doc: dict[str, Any]) -> Any:
    brand = doc.get("brand")
    logo = brand.get("logo") if isinstance(brand, Mapping) else None
    return logo.get("position") if isinstance(logo, Mapping) else None


def _upgrade(doc: dict[str, Any]) -> None:
    """Moves an older version to the current one in place. Any other version is left for `parse_theme` to reject."""
    version = doc.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version < SCHEMA_VERSION:
        return
    if version == 1:
        typography = copy.deepcopy(_TYPOGRAPHY_V2)
        typography["elements"]["business_name"]["align"] = "left" if _logo_position(doc) == "left" else "center"
        doc["typography"] = typography
    if version <= 2:
        doc["layout"] = copy.deepcopy(_LAYOUT_V3)
    if version <= 3:
        doc["cards"] = copy.deepcopy(_CARDS_V4)
    doc["schema_version"] = SCHEMA_VERSION


def _remove_unavailable_images(doc: dict[str, Any], available: set[str]) -> tuple[str, ...]:
    brand = doc.get("brand")
    if not isinstance(brand, Mapping):
        return ()
    removed = []
    for slot in IMAGE_SLOTS:
        part = brand.get(slot)
        if not isinstance(part, dict):
            continue
        image_id = part.get("image_id")
        # Only text is an image id; anything else stays for `parse_theme` to reject.
        if isinstance(image_id, str) and image_id not in available:
            part["image_id"] = None
            if slot == "background" and part.get("kind") == "image":
                part["kind"] = "none"
            removed.append(slot)
    return tuple(removed)


def import_theme(raw: Any, tenant_id: uuid.UUID, available_images: set[str]) -> ImportedTheme:
    """Validates an exported document for this tenant, never changing `raw`. `available_images` are the images
    the tenant's themes (draft, published, history) still use: the only ones an imported theme may keep."""
    if not isinstance(raw, Mapping):
        return ImportedTheme(parse_theme(raw, tenant_id), ())  # raises, naming the document
    doc = copy.deepcopy(dict(raw))
    _upgrade(doc)
    removed = _remove_unavailable_images(doc, available_images)
    return ImportedTheme(parse_theme(doc, tenant_id), removed)
