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
    name="Clásico",
    description="Limpio y neutro, con acentos en naranja cálido. El diseño por defecto.",
    colors=_DEFAULT.colors,
    typography=_DEFAULT.typography,
    layout=_DEFAULT.layout,
    cards=_DEFAULT.cards,
)

FRESCO = ThemePreset(
    id="fresco",
    name="Fresco",
    description="Claro y limpio, con verde, fotos en tres columnas y botones suaves. Para pedir desde la mesa.",
    colors=Colors(
        mode="light",
        primary="#15803d",
        secondary="#14532d",
        accent="#f59e0b",
        background="#f1f5f2",
        surface="#ffffff",
        text="#111827",
        text_muted="#4b5563",
        price="#166534",
        button_bg="#d7ecdc",
        button_text="#14532d",
        button_hover="#c3e2cb",
        border="#e2e8e4",
        badge_bg="#fef3c7",
        badge_text="#92400e",
        cart_bg="#15803d",
        cart_text="#ffffff",
        gradient=_flat("#15803d", "#f59e0b"),
    ),
    typography=_one_font(
        "poppins",
        TextElements(
            business_name=_style("heading", 30, 600, 120, -10),
            category=_style("heading", 20, 600, 140),
            product_name=_style("heading", 14, 600, 143),
            description=_style("body", 12, 400, 133),
            price=_style("price", 16, 600, 150),
            button=_style("button", 14, 500, 143),
        ),
    ),
    # "bar": tablets keep the full width for the three columns; large screens still show the order beside the menu.
    layout=_layout("tabs", "grid", 3, "comfortable", "plain", "bar"),
    cards=_cards("vertical", ("landscape", "cover", "left"), "xl", "sm", ("none", "border"), "comfortable", 2, "bottom", ("text", "rounded"), "lift", "rise", "rounded"),
)

BRASA = ThemePreset(
    id="brasa",
    name="Brasa",
    description="Negro con naranja cobre y fotos en tarjetas de borde encendido, cuatro por fila. Para parrillas y restaurantes de noche.",
    colors=Colors(
        mode="dark",
        primary="#f08a3c",
        secondary="#f5c9a0",
        accent="#ffb066",
        background="#000000",
        surface="#1f1f1f",
        text="#ffffff",
        text_muted="#a8a8a8",
        price="#ffffff",
        button_bg="#f08a3c",
        button_text="#181818",
        button_hover="#f5a35f",
        border="#313131",
        badge_bg="#3a2412",
        badge_text="#f7c08a",
        cart_bg="#f08a3c",
        cart_text="#181818",
        gradient=_flat("#f08a3c", "#ffb066"),
    ),
    typography=_one_font(
        "geist",
        TextElements(
            business_name=_style("heading", 48, 600, 100, -25, align="center"),
            category=_style("heading", 30, 600, 120, -10, align="center"),
            product_name=_style("heading", 16, 500, 150),
            description=_style("body", 12, 400, 133),
            price=_style("price", 20, 600, 140),
            button=_style("button", 14, 600, 143, 60, transform="uppercase"),
        ),
    ),
    layout=_layout(
        "chips", "grid", 4, "comfortable", "plain", "floating",
        (_HERO, _welcome("Sabor llevado a la perfección", "Cortes, brasas y platos de la casa preparados al momento.", style="plain"), _MENU),
    ),
    cards=_cards("vertical", ("square", "cover", "left"), "xl", "none", ("thin", "primary"), "comfortable", 2, "bottom", ("icon", "rounded"), "lift", "rise", "pill"),
)

FIESTA = ThemePreset(
    id="fiesta",
    name="Fiesta",
    description="Colorido y festivo, con títulos condensados en mayúsculas. Para taquerías y comida callejera.",
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
    description="Tonos crema y café con títulos clásicos. Para cafeterías y panaderías.",
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

ANTOJO = ThemePreset(
    id="antojo",
    name="Antojo",
    description="Crema con naranja vivo, etiquetas verdes y cuatro columnas con barra lateral. Para comida rápida y antojos.",
    colors=Colors(
        mode="light",
        primary="#f26a1b",
        secondary="#1f5c2e",
        accent="#16a34a",
        background="#fff9f3",
        surface="#ffffff",
        text="#1c1917",
        text_muted="#57534e",
        price="#c2410c",
        button_bg="#f26a1b",
        button_text="#1c1208",
        button_hover="#f58540",
        border="#f4e3d3",
        badge_bg="#dcfce7",
        badge_text="#166534",
        cart_bg="#f26a1b",
        cart_text="#1c1208",
        gradient=_flat("#f26a1b", "#16a34a"),
    ),
    typography=_one_font(
        "poppins",
        TextElements(
            business_name=_style("heading", 36, 700, 110, -10),
            category=_style("heading", 20, 600, 140),
            product_name=_style("heading", 14, 600, 143),
            description=_style("body", 12, 400, 133),
            price=_style("price", 16, 700, 150),
            button=_style("button", 14, 600, 143),
        ),
    ),
    layout=_layout(
        "sidebar", "grid", 4, "comfortable", "plain", "panel",
        (_HERO, _welcome("Rico, rápido y a tu mesa", "Elige tus favoritos y arma tu pedido en un minuto."), _MENU),
    ),
    cards=_cards("vertical", ("square", "cover", "left"), "xl", "sm", ("none", "border"), "compact", 1, "bottom", ("icon", "rounded"), "lift", "fade", "rounded"),
)

VELADA = ThemePreset(
    id="velada",
    name="Velada",
    description="Oscuro y cálido, con ámbar, títulos clásicos y fotos a tarjeta completa. Para cenas y cocina de autor.",
    colors=Colors(
        mode="dark",
        primary="#f2994a",
        secondary="#f0d9bd",
        accent="#e2c08d",
        background="#131209",
        surface="#1f1f1f",
        text="#f7f1e8",
        text_muted="#b5aa9a",
        price="#f5b06c",
        button_bg="#f2994a",
        button_text="#131209",
        button_hover="#f6b071",
        border="#313131",
        badge_bg="#3b2a17",
        badge_text="#f3cf9f",
        cart_bg="#f2994a",
        cart_text="#131209",
        gradient=_flat("#f2994a", "#e2c08d"),
    ),
    typography=_one_font(
        "playfair_display",
        TextElements(
            business_name=_style("heading", 48, 700, 100, align="center"),
            category=_style("heading", 30, 600, 120, align="center"),
            product_name=_style("heading", 20, 600, 140),
            description=_style("body", 14, 400, 150),
            price=_style("price", 18, 700, 140),
            button=_style("button", 14, 600, 143, 80, transform="uppercase"),
        ),
    ),
    layout=_layout("sections", "carousel", 3, "spacious", "underline", "panel", (_HERO, _DIVIDER, _MENU)),
    cards=_cards("overlay", ("wide", "cover", "left"), "md", "lg", ("none", "border"), "spacious", 1, "bottom", ("text", "square"), "grow", "fade", "rounded", overlay_opacity=60),
)

# The order the gallery shows them: the default design, the two built from reference designs, then the rest.
# A short list on purpose: templates that only changed a color were removed.
PRESETS: tuple[ThemePreset, ...] = (CLASSIC, FRESCO, BRASA, FIESTA, CAFE, COSTA, ESENCIAL, ANTOJO, VELADA)
