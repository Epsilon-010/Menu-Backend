"""add cards to stored themes

Moves every stored theme document (draft and published) from schema_version 3 to 4 by adding the default
cards, which draw each product exactly as the menu did before the cards could be customized.
Downgrade removes the cards (whatever the admin set is lost) and goes back to version 3.

Revision ID: c5d18a7e4f20
Revises: 9c2e41b7d5a3
Create Date: 2026-10-29 19:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5d18a7e4f20'
down_revision: Union[str, Sequence[str], None] = '9c2e41b7d5a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A frozen copy of the default cards of schema_version 4 (the app's defaults may change later).
_CARDS = {
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


def upgrade() -> None:
    """Upgrade schema."""
    cards = json.dumps(_CARDS)
    for column in ("draft", "published"):
        op.execute(
            sa.text(
                f"UPDATE themes SET {column} = {column} || jsonb_build_object("
                f"'schema_version', 4, 'cards', CAST(:cards AS jsonb)) "
                f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '3'"
            ).bindparams(cards=cards)
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("draft", "published"):
        op.execute(
            f"UPDATE themes SET {column} = ({column} - 'cards') || '{{\"schema_version\": 3}}'::jsonb "
            f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '4'"
        )
