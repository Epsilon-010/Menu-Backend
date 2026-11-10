"""add blocks to stored themes

Moves every stored theme document (draft, published and every saved version in `theme_versions`) from
schema_version 4 to 5 by adding the default order of the card blocks and header blocks and no per-category
layout, which draw the menu exactly as before the blocks could be dragged.
Downgrade removes the three fields (any order or per-category layout the admin set is lost) and goes back to
version 4.

Revision ID: b7e3a91c4d52
Revises: 548bab5f5d29
Create Date: 2026-11-04 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e3a91c4d52'
down_revision: Union[str, Sequence[str], None] = '548bab5f5d29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copies of the defaults of schema_version 5 (the app's defaults may change later).
_CARD_BLOCKS = ["image", "heading", "description", "badges", "add_button"]
_HEADER_BLOCKS = ["banner", "name", "tagline", "welcome"]

# (table, JSONB column) of every stored theme document.
_DOCUMENTS = (("themes", "draft"), ("themes", "published"), ("theme_versions", "theme"))


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _DOCUMENTS:
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = jsonb_set(jsonb_set(jsonb_set({column}, "
                "'{cards,blocks}', CAST(:card_blocks AS jsonb)), "
                "'{layout,header_blocks}', CAST(:header_blocks AS jsonb)), "
                "'{layout,categories}', '{}'::jsonb) || '{\"schema_version\": 5}'::jsonb "
                f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '4'"
            ).bindparams(card_blocks=json.dumps(_CARD_BLOCKS), header_blocks=json.dumps(_HEADER_BLOCKS))
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column in _DOCUMENTS:
        op.execute(
            f"UPDATE {table} SET {column} = ({column} #- '{{cards,blocks}}' #- '{{layout,header_blocks}}' "
            f"#- '{{layout,categories}}') || '{{\"schema_version\": 4}}'::jsonb "
            f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '5'"
        )
