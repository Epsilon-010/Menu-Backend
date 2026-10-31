"""add queued_at to order_items

Revision ID: f7f7d880b795
Revises: d81f0160ea55
Create Date: 2026-10-30 16:36:27.274518

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7f7d880b795'
down_revision: Union[str, Sequence[str], None] = 'd81f0160ea55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing dishes entered the queue when their order was sent (the best known time for dishes added later).
    op.add_column('order_items', sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE order_items SET queued_at = orders.created_at FROM orders WHERE orders.id = order_items.order_id"
    )
    op.alter_column('order_items', 'queued_at', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('order_items', 'queued_at')
