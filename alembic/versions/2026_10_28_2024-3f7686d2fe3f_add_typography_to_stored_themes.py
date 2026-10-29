"""add typography to stored themes

Moves every stored theme document (draft and published) from schema_version 1 to 2 by adding the default
typography. The business name keeps following the logo position, as it did before typography existed.
Downgrade removes the typography (whatever the admin set is lost) and goes back to version 1.

Revision ID: 3f7686d2fe3f
Revises: 744ab3c2ac86
Create Date: 2026-10-28 20:24:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3f7686d2fe3f'
down_revision: Union[str, Sequence[str], None] = '744ab3c2ac86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _text(font: str, size: int, weight: int, line_height: int, letter_spacing: int = 0, align: str = "left") -> dict:
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


# A frozen copy of the default typography of schema_version 2 (the app's defaults may change later).
_TYPOGRAPHY = {
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


def _upgraded(column: str) -> str:
    return f"""
        {column} || jsonb_build_object(
            'schema_version', 2,
            'typography', jsonb_set(
                CAST(:typography AS jsonb),
                '{{elements,business_name,align}}',
                to_jsonb(CASE WHEN {column} #>> '{{brand,logo,position}}' = 'left' THEN 'left' ELSE 'center' END)
            )
        )
    """


def upgrade() -> None:
    """Upgrade schema."""
    typography = json.dumps(_TYPOGRAPHY)
    for column in ("draft", "published"):
        op.execute(
            sa.text(
                f"UPDATE themes SET {column} = {_upgraded(column)} "
                f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '1'"
            ).bindparams(typography=typography)
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("draft", "published"):
        op.execute(
            f"UPDATE themes SET {column} = ({column} - 'typography') || '{{\"schema_version\": 1}}'::jsonb "
            f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '2'"
        )
