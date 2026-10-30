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

SCHEMA_VERSION = 4

MODES = ("light", "dark")
LOGO_SIZES = ("sm", "md", "lg")
LOGO_POSITIONS = ("left", "center")
BANNER_HEIGHTS = ("sm", "md", "lg")
BACKGROUND_KINDS = ("none", "image", "pattern")
BACKGROUND_PATTERNS = ("dots", "grid", "stripes", "waves", "checks", "zigzag")

FONT_ROLES = ("heading", "body", "price", "button")
TEXT_ELEMENTS = ("business_name", "category", "product_name", "description", "price", "button")
FONT_STYLES = ("normal", "italic")
TEXT_TRANSFORMS = ("none", "uppercase", "lowercase", "capitalize")
TEXT_ALIGNS = ("left", "center", "right")
WEIGHTS = tuple(range(100, 1000, 100))

NAVIGATIONS = ("chips", "tabs", "sidebar", "sections")
PRODUCT_VIEWS = ("grid", "list", "carousel")
DENSITIES = ("compact", "comfortable", "spacious")
CATEGORY_HEADERS = ("plain", "underline", "band")
CART_STYLES = ("bar", "panel", "floating")
MIN_COLUMNS, MAX_COLUMNS = 1, 4  # the grid on wide screens; narrow screens show fewer

CARD_TEMPLATES = ("vertical", "horizontal", "overlay")
IMAGE_ASPECTS = ("square", "landscape", "wide")  # 1:1, 4:3, 16:9
IMAGE_FITS = ("cover", "contain")
IMAGE_POSITIONS = ("left", "right")  # beside the text, in the horizontal template
CARD_RADII = ("none", "sm", "md", "lg", "xl")
CARD_SHADOWS = ("none", "sm", "md", "lg")
BORDER_WIDTHS = ("none", "thin", "thick")
BORDER_COLORS = ("border", "primary", "accent")  # colors of the palette, never a free color
CARD_PADDINGS = ("compact", "comfortable", "spacious")
PRICE_POSITIONS = ("top", "bottom")
ADD_BUTTON_STYLES = ("text", "icon", "both")
ADD_BUTTON_SHAPES = ("square", "rounded", "pill")
CARD_HOVERS = ("none", "lift", "grow")
CARD_ANIMATIONS = ("none", "fade", "rise")
BADGE_SHAPES = ("pill", "rounded")
MIN_DESCRIPTION_LINES, MAX_DESCRIPTION_LINES = 0, 6  # 0 hides the description
MIN_OVERLAY_OPACITY, MAX_OVERLAY_OPACITY = 30, 90  # % of the scrim under the text of the overlay template

MIN_SCALE, MAX_SCALE = 80, 130  # % of every size
MIN_SIZE, MAX_SIZE = 10, 72  # px, before the scale
MIN_LINE_HEIGHT, MAX_LINE_HEIGHT = 100, 200  # % of the size
MIN_LETTER_SPACING, MAX_LETTER_SPACING = -50, 200  # thousandths of an em

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
class Font:
    """A curated Google Fonts family: the weights it really has and whether it has italics."""

    family: str
    weights: tuple[int, ...]
    italic: bool


def _span(low: int, high: int) -> tuple[int, ...]:
    return tuple(range(low, high + 1, 100))


# The curated list (ids are what the theme stores). Geist is the default: the menu looked like it before.
FONTS: dict[str, Font] = {
    "geist": Font("Geist", _span(100, 900), italic=False),
    "inter": Font("Inter", _span(100, 900), italic=True),
    "poppins": Font("Poppins", _span(100, 900), italic=True),
    "montserrat": Font("Montserrat", _span(100, 900), italic=True),
    "lato": Font("Lato", (100, 300, 400, 700, 900), italic=True),
    "nunito": Font("Nunito", _span(200, 900), italic=True),
    "playfair_display": Font("Playfair Display", _span(400, 900), italic=True),
    "lora": Font("Lora", _span(400, 700), italic=True),
    "merriweather": Font("Merriweather", (300, 400, 700, 900), italic=True),
    "oswald": Font("Oswald", _span(200, 700), italic=False),
    "bebas_neue": Font("Bebas Neue", (400,), italic=False),
    "pacifico": Font("Pacifico", (400,), italic=False),
    "caveat": Font("Caveat", _span(400, 700), italic=False),
}


@dataclass(frozen=True)
class RoleFonts:
    heading: str
    body: str
    price: str
    button: str


@dataclass(frozen=True)
class TextStyle:
    """How one element of the menu is written. `font` is a role, whose family is in `RoleFonts`."""

    font: str
    size: int
    weight: int
    style: str
    line_height: int
    letter_spacing: int
    transform: str
    align: str


@dataclass(frozen=True)
class TextElements:
    business_name: TextStyle
    category: TextStyle
    product_name: TextStyle
    description: TextStyle
    price: TextStyle
    button: TextStyle


@dataclass(frozen=True)
class Typography:
    scale: int
    fonts: RoleFonts
    elements: TextElements


@dataclass(frozen=True)
class Layout:
    """How the menu is arranged: category navigation, product view, spacing, sections shown and the cart."""

    navigation: str
    product_view: str
    columns: int
    density: str
    sticky_header: bool
    category_header: str
    show_banner: bool
    show_tagline: bool
    show_welcome: bool
    cart: str


@dataclass(frozen=True)
class CardImage:
    aspect: str
    fit: str
    position: str


@dataclass(frozen=True)
class CardBorder:
    width: str
    color: str


@dataclass(frozen=True)
class AddButton:
    style: str
    shape: str


@dataclass(frozen=True)
class Cards:
    """How each product card looks: its template, image, shape, add button, motion and badges."""

    template: str
    image: CardImage
    radius: str
    shadow: str
    border: CardBorder
    padding: str
    description_lines: int
    price_position: str
    add_button: AddButton
    hover: str
    animation: str
    overlay_opacity: int
    badge_shape: str


@dataclass(frozen=True)
class Theme:
    schema_version: int
    colors: Colors
    brand: Brand
    typography: Typography
    layout: Layout
    cards: Cards

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


def _text(font: str, size: int, weight: int, line_height: int, letter_spacing: int = 0, align: str = "left") -> TextStyle:
    return TextStyle(font, size, weight, "normal", line_height, letter_spacing, "none", align)


# The sizes, weights and spacing the menu had before typography could be customized.
_DEFAULT_TYPOGRAPHY = Typography(
    scale=100,
    fonts=RoleFonts(heading="geist", body="geist", price="geist", button="geist"),
    elements=TextElements(
        business_name=_text("heading", 30, 600, 120, -25, align="center"),
        category=_text("heading", 20, 600, 140, -25),
        product_name=_text("heading", 16, 600, 150),
        description=_text("body", 14, 400, 143),
        price=_text("price", 16, 600, 150),
        button=_text("button", 14, 600, 143),
    ),
)


# The arrangement the menu had before the layout could be customized.
DEFAULT_LAYOUT = Layout(
    navigation="chips",
    product_view="grid",
    columns=2,
    density="comfortable",
    sticky_header=True,
    category_header="plain",
    show_banner=True,
    show_tagline=True,
    show_welcome=True,
    cart="bar",
)


# The card the menu had before the cards could be customized.
DEFAULT_CARDS = Cards(
    template="vertical",
    image=CardImage(aspect="landscape", fit="cover", position="left"),
    radius="xl",
    shadow="none",
    border=CardBorder(width="thin", color="border"),
    padding="comfortable",
    description_lines=3,
    price_position="top",
    add_button=AddButton(style="both", shape="rounded"),
    hover="none",
    animation="none",
    overlay_opacity=60,
    badge_shape="pill",
)


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
        typography=_DEFAULT_TYPOGRAPHY,
        layout=DEFAULT_LAYOUT,
        cards=DEFAULT_CARDS,
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


def _parse_text_style(doc: _Reader, fonts: RoleFonts) -> TextStyle:
    role = doc.choice("font", FONT_ROLES)
    font = FONTS[getattr(fonts, role)]
    weight = doc.number("weight", WEIGHTS[0], WEIGHTS[-1])
    if weight not in font.weights:
        raise InvalidTheme(doc.name("weight"))
    style = doc.choice("style", FONT_STYLES)
    if style == "italic" and not font.italic:
        raise InvalidTheme(doc.name("style"))
    text_style = TextStyle(
        font=role,
        size=doc.number("size", MIN_SIZE, MAX_SIZE),
        weight=weight,
        style=style,
        line_height=doc.number("line_height", MIN_LINE_HEIGHT, MAX_LINE_HEIGHT),
        letter_spacing=doc.number("letter_spacing", MIN_LETTER_SPACING, MAX_LETTER_SPACING),
        transform=doc.choice("transform", TEXT_TRANSFORMS),
        align=doc.choice("align", TEXT_ALIGNS),
    )
    doc.done()
    return text_style


def _parse_typography(doc: _Reader) -> Typography:
    fonts_doc = doc.child("fonts")
    fonts = RoleFonts(**{role: fonts_doc.choice(role, tuple(FONTS)) for role in FONT_ROLES})
    fonts_doc.done()
    elements_doc = doc.child("elements")
    elements = TextElements(
        **{element: _parse_text_style(elements_doc.child(element), fonts) for element in TEXT_ELEMENTS}
    )
    elements_doc.done()
    typography = Typography(scale=doc.number("scale", MIN_SCALE, MAX_SCALE), fonts=fonts, elements=elements)
    doc.done()
    return typography


def _parse_layout(doc: _Reader) -> Layout:
    layout = Layout(
        navigation=doc.choice("navigation", NAVIGATIONS),
        product_view=doc.choice("product_view", PRODUCT_VIEWS),
        columns=doc.number("columns", MIN_COLUMNS, MAX_COLUMNS),
        density=doc.choice("density", DENSITIES),
        sticky_header=doc.flag("sticky_header"),
        category_header=doc.choice("category_header", CATEGORY_HEADERS),
        show_banner=doc.flag("show_banner"),
        show_tagline=doc.flag("show_tagline"),
        show_welcome=doc.flag("show_welcome"),
        cart=doc.choice("cart", CART_STYLES),
    )
    doc.done()
    return layout


def _parse_cards(doc: _Reader) -> Cards:
    image_doc = doc.child("image")
    image = CardImage(
        aspect=image_doc.choice("aspect", IMAGE_ASPECTS),
        fit=image_doc.choice("fit", IMAGE_FITS),
        position=image_doc.choice("position", IMAGE_POSITIONS),
    )
    image_doc.done()
    border_doc = doc.child("border")
    border = CardBorder(width=border_doc.choice("width", BORDER_WIDTHS), color=border_doc.choice("color", BORDER_COLORS))
    border_doc.done()
    button_doc = doc.child("add_button")
    add_button = AddButton(
        style=button_doc.choice("style", ADD_BUTTON_STYLES), shape=button_doc.choice("shape", ADD_BUTTON_SHAPES)
    )
    button_doc.done()
    cards = Cards(
        template=doc.choice("template", CARD_TEMPLATES),
        image=image,
        radius=doc.choice("radius", CARD_RADII),
        shadow=doc.choice("shadow", CARD_SHADOWS),
        border=border,
        padding=doc.choice("padding", CARD_PADDINGS),
        description_lines=doc.number("description_lines", MIN_DESCRIPTION_LINES, MAX_DESCRIPTION_LINES),
        price_position=doc.choice("price_position", PRICE_POSITIONS),
        add_button=add_button,
        hover=doc.choice("hover", CARD_HOVERS),
        animation=doc.choice("animation", CARD_ANIMATIONS),
        overlay_opacity=doc.number("overlay_opacity", MIN_OVERLAY_OPACITY, MAX_OVERLAY_OPACITY),
        badge_shape=doc.choice("badge_shape", BADGE_SHAPES),
    )
    doc.done()
    return cards


def parse_theme(raw: Any, tenant_id: uuid.UUID) -> Theme:
    """Validates a whole theme document (as JSON) for that tenant. Raises InvalidTheme naming the field."""
    doc = _Reader(raw, "")
    version = doc.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise InvalidTheme("schema_version")
    theme = Theme(
        schema_version=SCHEMA_VERSION,
        colors=_parse_colors(doc.child("colors")),
        brand=_parse_brand(doc.child("brand"), tenant_id),
        typography=_parse_typography(doc.child("typography")),
        layout=_parse_layout(doc.child("layout")),
        cards=_parse_cards(doc.child("cards")),
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
