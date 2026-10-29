"""add layout to stored themes

Moves every stored theme document (draft and published) from schema_version 2 to 3 by adding the default
layout, which arranges the menu exactly as it was before the layout could be customized.
Downgrade removes the layout (whatever the admin set is lost) and goes back to version 2.

Revision ID: 9c2e41b7d5a3
Revises: 3f7686d2fe3f
Create Date: 2026-10-29 17:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9c2e41b7d5a3'
down_revision: Union[str, Sequence[str], None] = '3f7686d2fe3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A frozen copy of the default layout of schema_version 3 (the app's defaults may change later).
_LAYOUT = {
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


def upgrade() -> None:
    """Upgrade schema."""
    layout = json.dumps(_LAYOUT)
    for column in ("draft", "published"):
        op.execute(
            sa.text(
                f"UPDATE themes SET {column} = {column} || jsonb_build_object("
                f"'schema_version', 3, 'layout', CAST(:layout AS jsonb)) "
                f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '2'"
            ).bindparams(layout=layout)
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("draft", "published"):
        op.execute(
            f"UPDATE themes SET {column} = ({column} - 'layout') || '{{\"schema_version\": 2}}'::jsonb "
            f"WHERE {column} IS NOT NULL AND {column} ->> 'schema_version' = '3'"
        )
