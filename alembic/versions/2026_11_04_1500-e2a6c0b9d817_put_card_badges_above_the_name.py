"""put card badges above the name

The first default order of the card blocks (b7e3a91c4d52) drew the badges below the description, while every card
before schema_version 5 drew them above the name. Documents still on that first default order (draft, published
and every saved version in `theme_versions`) get the badges back above the name; an order the admin chose stays.
Downgrade turns the new default back into the first one.

Revision ID: e2a6c0b9d817
Revises: b7e3a91c4d52
Create Date: 2026-11-04 15:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2a6c0b9d817'
down_revision: Union[str, Sequence[str], None] = 'b7e3a91c4d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copies: the app's default may change later.
_FIRST_DEFAULT = ["image", "heading", "description", "badges", "add_button"]
_BADGES_ABOVE_NAME = ["image", "badges", "heading", "description", "add_button"]

# (table, JSONB column) of every stored theme document.
_DOCUMENTS = (("themes", "draft"), ("themes", "published"), ("theme_versions", "theme"))


def _replace(old: list[str], new: list[str]) -> None:
    for table, column in _DOCUMENTS:
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = jsonb_set({column}, '{{cards,blocks}}', CAST(:new AS jsonb)) "
                f"WHERE {column} IS NOT NULL AND {column} -> 'cards' -> 'blocks' = CAST(:old AS jsonb)"
            ).bindparams(old=json.dumps(old), new=json.dumps(new))
        )


def upgrade() -> None:
    """Upgrade schema."""
    _replace(_FIRST_DEFAULT, _BADGES_ABOVE_NAME)


def downgrade() -> None:
    """Downgrade schema."""
    _replace(_BADGES_ABOVE_NAME, _FIRST_DEFAULT)
