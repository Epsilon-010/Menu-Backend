"""add sections to stored themes

Moves every stored theme document (draft, published and every saved version in `theme_versions`) from
schema_version 5 to 6 by adding the menu page as a list of sections: the header, then the menu, which draws the
page exactly as before sections existed.
Downgrade removes the sections (any section the admin added is lost) and goes back to version 5.

Revision ID: 5d0e7a3c9b14
Revises: de3bacf10d81
Create Date: 2026-11-10 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5d0e7a3c9b14'
down_revision: Union[str, Sequence[str], None] = 'de3bacf10d81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of the default page of schema_version 6 (the app's defaults may change later).
_SECTIONS = [
    {"id": "00000000-0000-4000-8000-000000000001", "type": "hero"},
    {"id": "00000000-0000-4000-8000-000000000002", "type": "menu"},
]

# (table, JSONB column) of every stored theme document.
_DOCUMENTS = (("themes", "draft"), ("themes", "published"), ("theme_versions", "theme"))


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _DOCUMENTS:
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = jsonb_set({column}, '{{layout,sections}}', CAST(:sections AS jsonb)) "
                "|| '{\"schema_version\": 6}'::jsonb "
                f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '5'"
            ).bindparams(sections=json.dumps(_SECTIONS))
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column in _DOCUMENTS:
        op.execute(
            f"UPDATE {table} SET {column} = ({column} #- '{{layout,sections}}') || '{{\"schema_version\": 5}}'::jsonb "
            f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '6'"
        )
