"""Presets: complete designs (palette, mode, typography, layout and cards) an admin starts from instead of designing from scratch.

A preset never carries brand content (name, texts, images): applying one keeps the tenant's brand. Every preset is
a valid theme and readable (WCAG AA); the tests check it, so a new preset cannot ship inconsistent.
"""

from dataclasses import asdict, dataclass, replace
from typing import Any

from app.modules.theming.domain.theme import (
    DEFAULT_CARDS,
    DEFAULT_LAYOUT,
    DEFAULT_SECTIONS,
    AddButton,
    CardBorder,
    CardImage,
    Cards,
    Colors,
    DividerSection,
    Gradient,
    Layout,
    RoleFonts,
    Section,
    TextElements,
    TextSection,
    TextStyle,
    Theme,
    Typography,
    cards_to_dict,
    colors_to_dict,
    default_theme,
    layout_to_dict,
)


@dataclass(frozen=True)
class ThemePreset:
    id: str
    name: str
    description: str
    colors: Colors
    typography: Typography
    layout: Layout
    cards: Cards

    def apply(self, theme: Theme) -> Theme:
        return replace(theme, colors=self.colors, typography=self.typography, layout=self.layout, cards=self.cards)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "colors": colors_to_dict(self.colors),
            "typography": asdict(self.typography),
            "layout": layout_to_dict(self.layout),
            "cards": cards_to_dict(self.cards),
        }


def _style(
    font: str,
    size: int,
    weight: int,
    line_height: int,
    letter_spacing: int = 0,
    *,
    style: str = "normal",
    transform: str = "none",
    align: str = "left",
) -> TextStyle:
    return TextStyle(font, size, weight, style, line_height, letter_spacing, transform, align)


def _layout(
    navigation: str,
    product_view: str,
    columns: int,
    density: str,
    category_header: str,
    cart: str,
    sections: tuple[Section, ...] = DEFAULT_SECTIONS,
) -> Layout:
    return replace(
        DEFAULT_LAYOUT,
        navigation=navigation,
        product_view=product_view,
        columns=columns,
        density=density,
        category_header=category_header,
        cart=cart,
        sections=sections,
    )


# Pages of the templates. Ids only need to be unique within one theme; the header and menu keep the default ones.
_HERO, _MENU = DEFAULT_SECTIONS
_DIVIDER = DividerSection(id="00000000-0000-4000-8000-000000000004")


def _welcome(title: str, body: str, style: str = "highlight") -> TextSection:
    return TextSection(id="00000000-0000-4000-8000-000000000003", title=title, body=body, align="center", style=style)


def _one_font(font: str, elements: TextElements) -> Typography:
    """One typeface for every role: the templates follow the design system (no pairing, no italics, at most bold)."""
    return Typography(scale=100, fonts=RoleFonts(heading=font, body=font, price=font, button=font), elements=elements)


def _cards(
    template: str,
    image: tuple[str, str, str],
    radius: str,
    shadow: str,
    border: tuple[str, str],
    padding: str,
    description_lines: int,
    price_position: str,
    add_button: tuple[str, str],
    hover: str,
    animation: str,
    badge_shape: str,
    overlay_opacity: int = DEFAULT_CARDS.overlay_opacity,
) -> Cards:
    return Cards(
        template=template,
        image=CardImage(*image),
        radius=radius,
        shadow=shadow,
        border=CardBorder(*border),
        padding=padding,
        description_lines=description_lines,
        price_position=price_position,
        add_button=AddButton(*add_button),
        hover=hover,
        animation=animation,
        overlay_opacity=overlay_opacity,
        badge_shape=badge_shape,
        blocks=DEFAULT_CARDS.blocks,
    )


def _flat(color: str, to: str) -> Gradient:
    return Gradient(enabled=False, from_color=color, to_color=to, angle=135)


_DEFAULT = default_theme()

CLASSIC = ThemePreset(
    id="classic",
    name="Classic",
    description="Clean and neutral, with warm orange accents. The default design.",
    colors=_DEFAULT.colors,
    typography=_DEFAULT.typography,
    layout=_DEFAULT.layout,
    cards=_DEFAULT.cards,
)

BISTRO = ThemePreset(
    id="bistro",
    name="Bistro",
    description="Dark and elegant, with gold accents and serif titles.",
    colors=Colors(
        mode="dark",
        primary="#d4a056",
        secondary="#e8dcc8",
        accent="#c9a227",
        background="#14110f",
        surface="#1f1b18",
        text="#f5efe6",
        text_muted="#b8ab99",
        price="#e0b46a",
        button_bg="#d4a056",
        button_text="#14110f",
        button_hover="#e6bf80",
        border="#3a322b",
        badge_bg="#3b2f1c",
        badge_text="#f2d49b",
        cart_bg="#f5efe6",
        cart_text="#14110f",
        gradient=_flat("#d4a056", "#c9a227"),
    ),
    typography=Typography(
        scale=100,
        fonts=RoleFonts(heading="playfair_display", body="lato", price="playfair_display", button="lato"),
        elements=TextElements(
            business_name=_style("heading", 34, 700, 115, style="italic", align="center"),
            category=_style("heading", 24, 600, 130),
            product_name=_style("heading", 18, 600, 140),
            description=_style("body", 14, 400, 150),
            price=_style("price", 17, 700, 140),
            button=_style("button", 13, 700, 143, 80, transform="uppercase"),
        ),
    ),
    layout=_layout("sidebar", "list", 1, "spacious", "underline", "panel"),
    cards=_cards("horizontal", ("square", "cover", "right"), "md", "none", ("thin", "border"), "spacious", 2, "top", ("text", "square"), "none", "fade", "rounded"),
)

FIESTA = ThemePreset(
    id="fiesta",
    name="Fiesta",
    description="Bright and festive, with bold condensed titles. Great for taquerias and street food.",
    colors=Colors(
        mode="light",
        primary="#c2255c",
        secondary="#0f766e",
        accent="#f59f00",
        background="#fff8ef",
        surface="#ffffff",
        text="#2b1608",
        text_muted="#6b4a33",
        price="#a61e4d",
        button_bg="#c2255c",
        button_text="#ffffff",
        button_hover="#a61e4d",
        border="#f3d9c4",
        badge_bg="#fff3bf",
        badge_text="#8a4b00",
        cart_bg="#0f766e",
        cart_text="#ffffff",
        gradient=_flat("#c2255c", "#f59f00"),
    ),
    typography=Typography(
        scale=100,
        fonts=RoleFonts(heading="bebas_neue", body="nunito", price="bebas_neue", button="nunito"),
        elements=TextElements(
            business_name=_style("heading", 44, 400, 100, 40, align="center"),
            category=_style("heading", 30, 400, 110, 40),
            product_name=_style("heading", 22, 400, 120, 30),
            description=_style("body", 14, 400, 150),
            price=_style("price", 22, 400, 120, 30),
            button=_style("button", 14, 800, 143, 20),
        ),
    ),
    layout=_layout("chips", "carousel", 2, "comfortable", "band", "floating"),
    cards=_cards("overlay", ("landscape", "cover", "left"), "xl", "lg", ("none", "border"), "comfortable", 2, "bottom", ("both", "pill"), "grow", "rise", "pill", overlay_opacity=70),
)

CAFE = ThemePreset(
    id="cafe",
    name="Café",
    description="Cozy cream and coffee tones with classic serif titles.",
    colors=Colors(
        mode="light",
        primary="#7c4a2d",
        secondary="#3f5d45",
        accent="#c08552",
        background="#f6efe6",
        surface="#fffaf3",
        text="#2d2118",
        text_muted="#6b5848",
        price="#7c4a2d",
        button_bg="#6f4428",
        button_text="#fffaf3",
        button_hover="#5a3620",
        border="#e6d8c6",
        badge_bg="#efe0cc",
        badge_text="#5a3620",
        cart_bg="#2d2118",
        cart_text="#fffaf3",
        gradient=_flat("#7c4a2d", "#c08552"),
    ),
    typography=Typography(
        scale=100,
        fonts=RoleFonts(heading="lora", body="lato", price="lora", button="lato"),
        elements=TextElements(
            business_name=_style("heading", 32, 700, 120, align="center"),
            category=_style("heading", 22, 600, 135),
            product_name=_style("heading", 17, 600, 145),
            description=_style("body", 14, 400, 155),
            price=_style("price", 16, 700, 150),
            button=_style("button", 14, 700, 143, 20),
        ),
    ),
    layout=_layout("sections", "grid", 3, "comfortable", "underline", "bar"),
    cards=_cards("vertical", ("square", "cover", "left"), "lg", "sm", ("thin", "border"), "comfortable", 3, "bottom", ("text", "rounded"), "lift", "fade", "pill"),
)

GARDEN = ThemePreset(
    id="garden",
    name="Garden",
    description="Fresh greens and rounded type. Made for healthy food, salads and juices.",
    colors=Colors(
        mode="light",
        primary="#2f855a",
        secondary="#1f3d2b",
        accent="#84cc16",
        background="#f4faf5",
        surface="#ffffff",
        text="#13261a",
        text_muted="#4a6352",
        price="#276749",
        button_bg="#276749",
        button_text="#ffffff",
        button_hover="#1f5139",
        border="#d7eadc",
        badge_bg="#e3f5d0",
        badge_text="#33601a",
        cart_bg="#1f3d2b",
        cart_text="#ffffff",
        gradient=_flat("#2f855a", "#84cc16"),
    ),
    typography=Typography(
        scale=100,
        fonts=RoleFonts(heading="poppins", body="inter", price="poppins", button="poppins"),
        elements=TextElements(
            business_name=_style("heading", 30, 700, 120, -10, align="center"),
            category=_style("heading", 20, 600, 140),
            product_name=_style("heading", 16, 600, 150),
            description=_style("body", 14, 400, 150),
            price=_style("price", 16, 600, 150),
            button=_style("button", 14, 600, 143),
        ),
    ),
    layout=_layout("tabs", "grid", 2, "spacious", "plain", "panel"),
    cards=_cards("vertical", ("wide", "cover", "left"), "xl", "md", ("none", "border"), "spacious", 3, "top", ("both", "pill"), "lift", "rise", "pill"),
)

STREET = ThemePreset(
    id="street",
    name="Street",
    description="Black and yellow with loud uppercase titles. Built for burgers, wings and late nights.",
    colors=Colors(
        mode="dark",
        primary="#facc15",
        secondary="#ef4444",
        accent="#f97316",
        background="#111111",
        surface="#1c1c1c",
        text="#ffffff",
        text_muted="#b3b3b3",
        price="#facc15",
        button_bg="#facc15",
        button_text="#111111",
        button_hover="#fde047",
        border="#333333",
        badge_bg="#3a1414",
        badge_text="#fca5a5",
        cart_bg="#facc15",
        cart_text="#111111",
        gradient=_flat("#facc15", "#f97316"),
    ),
    typography=Typography(
        scale=100,
        fonts=RoleFonts(heading="oswald", body="inter", price="oswald", button="oswald"),
        elements=TextElements(
            business_name=_style("heading", 36, 700, 110, 20, transform="uppercase", align="center"),
            category=_style("heading", 24, 600, 120, 30, transform="uppercase"),
            product_name=_style("heading", 18, 600, 130, 10, transform="uppercase"),
            description=_style("body", 14, 400, 150),
            price=_style("price", 18, 600, 130),
            button=_style("button", 14, 600, 143, 60, transform="uppercase"),
        ),
    ),
    layout=_layout("tabs", "list", 1, "compact", "band", "floating"),
    cards=_cards("horizontal", ("landscape", "cover", "left"), "none", "none", ("thick", "accent"), "compact", 2, "top", ("icon", "square"), "grow", "none", "rounded", overlay_opacity=80),
)

# --- Templates with their own page (sections), designed with the project's design system: one typeface each, no
# italics, at most bold, flat backgrounds, dark grounds from its palette and sizes on its type scale.

MERCADO = ThemePreset(
    id="mercado",
    name="Mercado",
    description="Terracota y verde con un mensaje de bienvenida. Para cocina casera y de mercado.",
    colors=Colors(
        mode="light",
        primary="#b4441c",
        secondary="#3d5a1e",
        accent="#e9a23b",
        background="#fbf6ef",
        surface="#ffffff",
        text="#2a1a10",
        text_muted="#6b5141",
        price="#9c3a17",
        button_bg="#b4441c",
        button_text="#ffffff",
        button_hover="#933615",
        border="#eddccb",
        badge_bg="#f4e7c5",
        badge_text="#6e4a06",
        cart_bg="#3d5a1e",
        cart_text="#ffffff",
        gradient=_flat("#b4441c", "#e9a23b"),
    ),
    typography=_one_font(
        "poppins",
        TextElements(
            business_name=_style("heading", 36, 700, 110, -10, align="center"),
            category=_style("heading", 24, 600, 130),
            product_name=_style("heading", 16, 600, 150),
            description=_style("body", 14, 400, 150),
            price=_style("price", 16, 700, 150),
            button=_style("button", 14, 600, 143),
        ),
    ),
    layout=_layout(
        "chips", "grid", 2, "comfortable", "band", "bar",
        (_HERO, _welcome("Hecho al momento", "Ingredientes del mercado, preparados cuando los pides."), _MENU),
    ),
    cards=_cards("vertical", ("landscape", "cover", "left"), "xl", "sm", ("thin", "border"), "comfortable", 2, "top", ("both", "rounded"), "lift", "fade", "pill"),
)

NOCTURNO = ThemePreset(
    id="nocturno",
    name="Nocturno",
    description="Fondo oscuro con acentos coral y títulos en mayúsculas. Para bares y cenas.",
    colors=Colors(
        mode="dark",
        primary="#ff6b4a",
        secondary="#f5d0c5",
        accent="#ffb347",
        background="#181818",
        surface="#1f1f1f",
        text="#f5f5f5",
        text_muted="#a3a3a3",
        price="#ff8a6e",
        button_bg="#ff6b4a",
        button_text="#181818",
        button_hover="#ff8a6e",
        border="#313131",
        badge_bg="#3a2420",
        badge_text="#ffc4b5",
        cart_bg="#ff6b4a",
        cart_text="#181818",
        gradient=_flat("#ff6b4a", "#ffb347"),
    ),
    typography=_one_font(
        "montserrat",
        TextElements(
            business_name=_style("heading", 36, 700, 110, 20, transform="uppercase", align="center"),
            category=_style("heading", 20, 700, 130, 60, transform="uppercase"),
            product_name=_style("heading", 16, 600, 150),
            description=_style("body", 14, 400, 150),
            price=_style("price", 16, 700, 150),
            button=_style("button", 14, 600, 143, 40, transform="uppercase"),
        ),
    ),
    layout=_layout("tabs", "grid", 2, "comfortable", "plain", "floating", (_HERO, _DIVIDER, _MENU)),
    cards=_cards("overlay", ("landscape", "cover", "left"), "lg", "md", ("none", "border"), "comfortable", 2, "bottom", ("icon", "pill"), "grow", "rise", "rounded", overlay_opacity=70),
)

COSTA = ThemePreset(
    id="costa",
    name="Costa",
    description="Azul mar y arena, con una lista fácil de leer. Para mariscos y cocina de playa.",
    colors=Colors(
        mode="light",
        primary="#0e6e8c",
        secondary="#12475a",
        accent="#f2b134",
        background="#f3f8fa",
        surface="#ffffff",
        text="#0f2a35",
        text_muted="#4b6470",
        price="#0b5c75",
        button_bg="#0e6e8c",
        button_text="#ffffff",
        button_hover="#0b5c75",
        border="#d5e6ec",
        badge_bg="#fdf0cf",
        badge_text="#7a5300",
        cart_bg="#12475a",
        cart_text="#ffffff",
        gradient=_flat("#0e6e8c", "#f2b134"),
    ),
    typography=_one_font(
        "nunito",
        TextElements(
            business_name=_style("heading", 36, 700, 110, align="center"),
            category=_style("heading", 24, 700, 130),
            product_name=_style("heading", 18, 700, 140),
            description=_style("body", 14, 400, 150),
            price=_style("price", 18, 700, 140),
            button=_style("button", 14, 700, 143),
        ),
    ),
    layout=_layout(
        "sections", "list", 1, "comfortable", "underline", "panel",
        (_HERO, _welcome("Del mar a tu mesa", "Pescados y mariscos frescos todos los días.", style="plain"), _MENU),
    ),
    cards=_cards("horizontal", ("square", "cover", "left"), "md", "none", ("thin", "border"), "comfortable", 2, "top", ("text", "rounded"), "none", "fade", "pill"),
)

HORNO = ThemePreset(
    id="horno",
    name="Horno",
    description="Crema y café con títulos clásicos y un aviso del día. Para panaderías y desayunos.",
    colors=Colors(
        mode="light",
        primary="#8a4b21",
        secondary="#4a3424",
        accent="#d29a4a",
        background="#f8f1e7",
        surface="#fffbf5",
        text="#2e1f14",
        text_muted="#6e5a49",
        price="#8a4b21",
        button_bg="#8a4b21",
        button_text="#fffbf5",
        button_hover="#6e3a18",
        border="#ead9c3",
        badge_bg="#f1e2c9",
        badge_text="#6e3a18",
        cart_bg="#2e1f14",
        cart_text="#fffbf5",
        gradient=_flat("#8a4b21", "#d29a4a"),
    ),
    typography=_one_font(
        "merriweather",
        TextElements(
            business_name=_style("heading", 30, 700, 120, align="center"),
            category=_style("heading", 20, 700, 140),
            product_name=_style("heading", 16, 700, 150),
            description=_style("body", 14, 400, 160),
            price=_style("price", 16, 700, 150),
            button=_style("button", 14, 700, 143),
        ),
    ),
    layout=_layout(
        "chips", "grid", 3, "comfortable", "underline", "bar",
        (_HERO, _welcome("Recién horneado", "Pan, café y postres hechos cada mañana en casa."), _DIVIDER, _MENU),
    ),
    cards=_cards("vertical", ("square", "cover", "left"), "xl", "none", ("thin", "border"), "comfortable", 2, "bottom", ("both", "rounded"), "lift", "fade", "rounded"),
)

ESENCIAL = ThemePreset(
    id="esencial",
    name="Esencial",
    description="Blanco y negro, sin adornos: los productos en una lista compacta. Para cualquier negocio.",
    colors=Colors(
        mode="light",
        primary="#18181b",
        secondary="#18181b",
        accent="#71717a",
        background="#ffffff",
        surface="#ffffff",
        text="#18181b",
        text_muted="#52525b",
        price="#18181b",
        button_bg="#18181b",
        button_text="#ffffff",
        button_hover="#3f3f46",
        border="#e4e4e7",
        badge_bg="#f4f4f5",
        badge_text="#3f3f46",
        cart_bg="#18181b",
        cart_text="#ffffff",
        gradient=_flat("#18181b", "#71717a"),
    ),
    typography=_one_font(
        "geist",
        TextElements(
            business_name=_style("heading", 30, 600, 120, -25, align="center"),
            category=_style("heading", 18, 600, 140, 80, transform="uppercase"),
            product_name=_style("heading", 16, 500, 150),
            description=_style("body", 14, 400, 143),
            price=_style("price", 16, 500, 150),
            button=_style("button", 14, 600, 143),
        ),
    ),
    layout=_layout("sections", "list", 1, "compact", "plain", "bar"),
    cards=_cards("horizontal", ("square", "cover", "right"), "sm", "none", ("thin", "border"), "compact", 2, "top", ("icon", "rounded"), "none", "none", "rounded"),
)

TEMPORADA = ThemePreset(
    id="temporada",
    name="Temporada",
    description="Fondo oscuro cálido, rojo intenso y una carta con barra lateral. Para cocina de autor.",
    colors=Colors(
        mode="dark",
        primary="#e0503d",
        secondary="#ead9b8",
        accent="#c9a86a",
        background="#131209",
        surface="#1f1f1f",
        text="#f3ece0",
        text_muted="#b0a594",
        price="#f0806f",
        button_bg="#c43d2b",
        button_text="#ffffff",
        button_hover="#a83324",
        border="#313131",
        badge_bg="#3a2a1a",
        badge_text="#e8c98f",
        cart_bg="#f3ece0",
        cart_text="#131209",
        gradient=_flat("#e0503d", "#c9a86a"),
    ),
    typography=_one_font(
        "lora",
        TextElements(
            business_name=_style("heading", 36, 700, 110, align="center"),
            category=_style("heading", 24, 600, 130),
            product_name=_style("heading", 18, 600, 140),
            description=_style("body", 14, 400, 155),
            price=_style("price", 18, 700, 140),
            button=_style("button", 14, 600, 143, 40, transform="uppercase"),
        ),
    ),
    layout=_layout(
        "sidebar", "list", 1, "spacious", "underline", "panel",
        (_HERO, _welcome("Cocina de temporada", "Cada plato se prepara al momento con ingredientes frescos.", style="plain"), _MENU),
    ),
    cards=_cards("horizontal", ("square", "cover", "left"), "md", "none", ("thin", "border"), "spacious", 2, "top", ("text", "square"), "none", "fade", "rounded"),
)

# The order the gallery shows them; the default design comes first.
PRESETS: tuple[ThemePreset, ...] = (CLASSIC, BISTRO, FIESTA, CAFE, GARDEN, STREET, MERCADO, NOCTURNO, COSTA, HORNO, ESENCIAL, TEMPORADA)
