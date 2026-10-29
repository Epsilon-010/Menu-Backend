"""Presets: complete designs (palette, mode and typography) an admin starts from instead of designing from scratch.

A preset never carries brand content (name, texts, images): applying one keeps the tenant's brand. Every preset is
a valid theme and readable (WCAG AA); the tests check it, so a new preset cannot ship inconsistent.
"""

from dataclasses import asdict, dataclass, replace
from typing import Any

from app.modules.theming.domain.theme import (
    Colors,
    Gradient,
    RoleFonts,
    TextElements,
    TextStyle,
    Theme,
    Typography,
    colors_to_dict,
    default_theme,
)


@dataclass(frozen=True)
class ThemePreset:
    id: str
    name: str
    description: str
    colors: Colors
    typography: Typography

    def apply(self, theme: Theme) -> Theme:
        return replace(theme, colors=self.colors, typography=self.typography)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "colors": colors_to_dict(self.colors),
            "typography": asdict(self.typography),
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


def _flat(color: str, to: str) -> Gradient:
    return Gradient(enabled=False, from_color=color, to_color=to, angle=135)


_DEFAULT = default_theme()

CLASSIC = ThemePreset(
    id="classic",
    name="Classic",
    description="Clean and neutral, with warm orange accents. The default design.",
    colors=_DEFAULT.colors,
    typography=_DEFAULT.typography,
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
)

# The order the gallery shows them; the default design comes first.
PRESETS: tuple[ThemePreset, ...] = (CLASSIC, BISTRO, FIESTA, CAFE, GARDEN, STREET)
