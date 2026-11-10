"""add cancelled_by to order items

Records the role (kitchen, waiter or admin) of whoever cancelled a dish, so a waiter's cancellation is not shown as
a kitchen rejection. Dishes cancelled before this stay null: the role was never stored on the dish.
Downgrade drops the column.

Revision ID: a41c7e9d2b60
Revises: 5d0e7a3c9b14
Create Date: 2026-11-10 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a41c7e9d2b60'
down_revision: Union[str, Sequence[str], None] = '5d0e7a3c9b14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('order_items', sa.Column('cancelled_by', sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column('order_items', 'cancelled_by')
