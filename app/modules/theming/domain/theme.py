"""The theme: how a tenant's table menu looks, as a versioned document of validated values only.

No CSS, HTML or URL ever enters a theme: colors are normalized to `#rrggbb`, choices come from fixed
lists, numbers from fixed ranges, and images are public ids inside the tenant's folder for that slot.
The frontend turns these values into CSS variables; nothing else from the theme reaches a style.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from app.shared.domain.images import ImageKind, InvalidImage, ensure_owned_image

SCHEMA_VERSION = 1

MODES = ("light", "dark")
LOGO_SIZES = ("sm", "md", "lg")
LOGO_POSITIONS = ("left", "center")
BANNER_HEIGHTS = ("sm", "md", "lg")
BACKGROUND_KINDS = ("none", "image", "pattern")
BACKGROUND_PATTERNS = ("dots", "grid", "stripes", "waves", "checks", "zigzag")

MAX_NAME_LENGTH = 60
MAX_TAGLINE_LENGTH = 120
MAX_WELCOME_LENGTH = 280
MAX_BLUR = 20

# WCAG AA for normal text.
MIN_CONTRAST = 4.5

_HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_RGB = re.compile(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)")
# Control characters (tab, newline, bell...) are not text a menu shows; the welcome message keeps newlines.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_CONTROL_BUT_NEWLINE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")


class InvalidTheme(ValueError):
    """A theme value is malformed or out of range. The message names the field, never the value."""

    def __init__(self, field: str) -> None:
        super().__init__(f"Invalid theme value: {field}")
        self.field = field


@dataclass(frozen=True)
class Gradient:
    enabled: bool
    from_color: str
    to_color: str
    angle: int


@dataclass(frozen=True)
class Colors:
    mode: str
    primary: str
    secondary: str
    accent: str
    background: str
    surface: str
    text: str
    text_muted: str
    price: str
    button_bg: str
    button_text: str
    button_hover: str
    border: str
    badge_bg: str
    badge_text: str
    cart_bg: str
    cart_text: str
    gradient: Gradient


@dataclass(frozen=True)
class Logo:
    image_id: str | None
    size: str
    position: str


@dataclass(frozen=True)
class Banner:
    image_id: str | None
    height: str
    overlay_color: str
    overlay_opacity: int


@dataclass(frozen=True)
class Background:
    kind: str
    image_id: str | None
    pattern: str
    opacity: int
    blur: int


@dataclass(frozen=True)
class Brand:
    name: str
    tagline: str
    welcome_message: str
    logo: Logo
    banner: Banner
    background: Background


@dataclass(frozen=True)
class Theme:
    schema_version: int
    colors: Colors
    brand: Brand

    def images(self) -> dict[str, ImageKind]:
        """Every image the theme uses, with the slot (folder) it belongs to."""
        slots = (
            (self.brand.logo.image_id, ImageKind.LOGO),
            (self.brand.banner.image_id, ImageKind.BANNER),
            (self.brand.background.image_id, ImageKind.BACKGROUND),
        )
        return {public_id: kind for public_id, kind in slots if public_id is not None}

    def image_ids(self) -> set[str]:
        return set(self.images())

    def to_dict(self) -> dict[str, Any]:
        doc = asdict(self)
        doc["colors"] = colors_to_dict(self.colors)
        return doc


def colors_to_dict(colors: Colors) -> dict[str, Any]:
    """The colors as the theme document (JSON) names them."""
    doc = asdict(colors)
    gradient = doc["gradient"]
    gradient["from"] = gradient.pop("from_color")
    gradient["to"] = gradient.pop("to_color")
    return doc


@dataclass(frozen=True)
class ContrastWarning:
    """A text color that is hard to read on its background (below WCAG AA)."""

    foreground: str
    background: str
    ratio: float


_LIGHT = Colors(
    mode="light",
    primary="#c2410c",
    secondary="#1f2937",
    accent="#f59e0b",
    background="#fafaf9",
    surface="#ffffff",
    text="#18181b",
    text_muted="#52525b",
    price="#9a3412",
    button_bg="#c2410c",
    button_text="#ffffff",
    button_hover="#9a3412",
    border="#e4e4e7",
    badge_bg="#fef3c7",
    badge_text="#92400e",
    cart_bg="#18181b",
    cart_text="#ffffff",
    gradient=Gradient(enabled=False, from_color="#c2410c", to_color="#f59e0b", angle=135),
)

_DARK = Colors(
    mode="dark",
    primary="#fb923c",
    secondary="#e4e4e7",
    accent="#fbbf24",
    background="#09090b",
    surface="#18181b",
    text="#fafafa",
    text_muted="#a1a1aa",
    price="#fdba74",
    button_bg="#fb923c",
    button_text="#09090b",
    button_hover="#fdba74",
    border="#3f3f46",
    badge_bg="#422006",
    badge_text="#fde68a",
    cart_bg="#fafafa",
    cart_text="#09090b",
    gradient=Gradient(enabled=False, from_color="#fb923c", to_color="#fbbf24", angle=135),
)


def default_colors(mode: str) -> Colors:
    """The starting palette of each mode (switching mode in the editor starts from it)."""
    return _DARK if mode == "dark" else _LIGHT


def default_theme() -> Theme:
    return Theme(
        schema_version=SCHEMA_VERSION,
        colors=_LIGHT,
        brand=Brand(
            name="",
            tagline="",
            welcome_message="",
            logo=Logo(image_id=None, size="md", position="center"),
            banner=Banner(image_id=None, height="md", overlay_color="#000000", overlay_opacity=30),
            background=Background(kind="none", image_id=None, pattern="dots", opacity=10, blur=0),
        ),
    )


# --- Parsing: every field is required, unknown fields are rejected ------------------------------------


class _Reader:
    """Reads one object of the document, naming fields by their full path in errors."""

    def __init__(self, raw: Any, path: str) -> None:
        if not isinstance(raw, Mapping):
            raise InvalidTheme(path or "theme")
        self._raw = raw
        self._path = path
        self._read: set[str] = set()

    def name(self, key: str) -> str:
        return f"{self._path}.{key}" if self._path else key

    def get(self, key: str) -> Any:
        if key not in self._raw:
            raise InvalidTheme(self.name(key))
        self._read.add(key)
        return self._raw[key]

    def child(self, key: str) -> "_Reader":
        return _Reader(self.get(key), self.name(key))

    def done(self) -> None:
        for key in self._raw:
            if key not in self._read:
                raise InvalidTheme(self.name(str(key)))

    def color(self, key: str) -> str:
        value = self.get(key)
        if isinstance(value, str):
            text = value.strip()
            if (match := _HEX.fullmatch(text)) is not None:
                digits = match.group(1).lower()
                return "#" + (digits if len(digits) == 6 else "".join(c * 2 for c in digits))
            if (match := _RGB.fullmatch(text)) is not None:
                channels = [int(group) for group in match.groups()]
                if all(channel <= 255 for channel in channels):
                    return "#" + "".join(f"{channel:02x}" for channel in channels)
        raise InvalidTheme(self.name(key))

    def choice(self, key: str, options: tuple[str, ...]) -> str:
        value = self.get(key)
        if not isinstance(value, str) or value not in options:
            raise InvalidTheme(self.name(key))
        return value

    def number(self, key: str, low: int, high: int) -> int:
        value = self.get(key)
        # bool is an int in Python; a theme never takes true/false as a number.
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise InvalidTheme(self.name(key))
        return value

    def flag(self, key: str) -> bool:
        value = self.get(key)
        if not isinstance(value, bool):
            raise InvalidTheme(self.name(key))
        return value

    def text(self, key: str, max_length: int, *, multiline: bool = False) -> str:
        value = self.get(key)
        if not isinstance(value, str):
            raise InvalidTheme(self.name(key))
        text = value.strip()
        control = _CONTROL_BUT_NEWLINE if multiline else _CONTROL
        if len(text) > max_length or control.search(text):
            raise InvalidTheme(self.name(key))
        return text

    def image(self, key: str, tenant_id: uuid.UUID, kind: ImageKind) -> str | None:
        value = self.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidTheme(self.name(key))
        try:
            return ensure_owned_image(tenant_id, kind, value)
        except InvalidImage as error:
            raise InvalidTheme(self.name(key)) from error


def _parse_colors(doc: _Reader) -> Colors:
    gradient_doc = doc.child("gradient")
    gradient = Gradient(
        enabled=gradient_doc.flag("enabled"),
        from_color=gradient_doc.color("from"),
        to_color=gradient_doc.color("to"),
        angle=gradient_doc.number("angle", 0, 360),
    )
    gradient_doc.done()
    colors = Colors(
        mode=doc.choice("mode", MODES),
        primary=doc.color("primary"),
        secondary=doc.color("secondary"),
        accent=doc.color("accent"),
        background=doc.color("background"),
        surface=doc.color("surface"),
        text=doc.color("text"),
        text_muted=doc.color("text_muted"),
        price=doc.color("price"),
        button_bg=doc.color("button_bg"),
        button_text=doc.color("button_text"),
        button_hover=doc.color("button_hover"),
        border=doc.color("border"),
        badge_bg=doc.color("badge_bg"),
        badge_text=doc.color("badge_text"),
        cart_bg=doc.color("cart_bg"),
        cart_text=doc.color("cart_text"),
        gradient=gradient,
    )
    doc.done()
    return colors


def _parse_brand(doc: _Reader, tenant_id: uuid.UUID) -> Brand:
    logo_doc = doc.child("logo")
    logo = Logo(
        image_id=logo_doc.image("image_id", tenant_id, ImageKind.LOGO),
        size=logo_doc.choice("size", LOGO_SIZES),
        position=logo_doc.choice("position", LOGO_POSITIONS),
    )
    logo_doc.done()

    banner_doc = doc.child("banner")
    banner = Banner(
        image_id=banner_doc.image("image_id", tenant_id, ImageKind.BANNER),
        height=banner_doc.choice("height", BANNER_HEIGHTS),
        overlay_color=banner_doc.color("overlay_color"),
        overlay_opacity=banner_doc.number("overlay_opacity", 0, 100),
    )
    banner_doc.done()

    background_doc = doc.child("background")
    background = Background(
        kind=background_doc.choice("kind", BACKGROUND_KINDS),
        image_id=background_doc.image("image_id", tenant_id, ImageKind.BACKGROUND),
        pattern=background_doc.choice("pattern", BACKGROUND_PATTERNS),
        opacity=background_doc.number("opacity", 0, 100),
        blur=background_doc.number("blur", 0, MAX_BLUR),
    )
    background_doc.done()
    if background.kind == "image" and background.image_id is None:
        raise InvalidTheme(background_doc.name("image_id"))

    brand = Brand(
        name=doc.text("name", MAX_NAME_LENGTH),
        tagline=doc.text("tagline", MAX_TAGLINE_LENGTH),
        welcome_message=doc.text("welcome_message", MAX_WELCOME_LENGTH, multiline=True),
        logo=logo,
        banner=banner,
        background=background,
    )
    doc.done()
    return brand


def parse_theme(raw: Any, tenant_id: uuid.UUID) -> Theme:
    """Validates a whole theme document (as JSON) for that tenant. Raises InvalidTheme naming the field."""
    doc = _Reader(raw, "")
    version = doc.get("schema_version")
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise InvalidTheme("schema_version")
    theme = Theme(
        schema_version=SCHEMA_VERSION,
        colors=_parse_colors(doc.child("colors")),
        brand=_parse_brand(doc.child("brand"), tenant_id),
    )
    doc.done()
    return theme


# --- Contrast (WCAG 2.x relative luminance) -------------------------------------------------------------

# (text color, background it sits on) as the menu draws them.
_READABLE_PAIRS = (
    ("text", "background"),
    ("text", "surface"),
    ("text_muted", "surface"),
    ("price", "surface"),
    ("button_text", "button_bg"),
    ("badge_text", "badge_bg"),
    ("cart_text", "cart_bg"),
)


def _luminance(color: str) -> float:
    def channel(hex_pair: str) -> float:
        value = int(hex_pair, 16) / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(color[i : i + 2]) for i in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_warnings(colors: Colors) -> list[ContrastWarning]:
    """Pairs below WCAG AA. Only a warning for the admin: the theme is still saved."""
    warnings = []
    for foreground, background in _READABLE_PAIRS:
        ratio = contrast_ratio(getattr(colors, foreground), getattr(colors, background))
        if ratio < MIN_CONTRAST:
            warnings.append(ContrastWarning(foreground, background, round(ratio, 2)))
    return warnings
