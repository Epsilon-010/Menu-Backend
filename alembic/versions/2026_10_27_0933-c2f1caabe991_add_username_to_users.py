"""add username to users

Revision ID: c2f1caabe991
Revises: 1ee0aeda53d1
Create Date: 2026-10-27 09:33:17.010490

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f1caabe991'
down_revision: Union[str, Sequence[str], None] = '1ee0aeda53d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('username', sa.String(length=40), nullable=True))
    op.alter_column('users', 'email',
               existing_type=sa.VARCHAR(length=254),
               nullable=True)
    op.create_unique_constraint(op.f('uq_users_username'), 'users', ['username'])
    op.create_check_constraint(op.f('ck_users_login'), 'users', 'email IS NOT NULL OR username IS NOT NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_users_login'), 'users', type_='check')
    # Accounts without an email (waiters, cooks) cannot exist in the previous schema;
    # their refresh tokens go with them (ON DELETE CASCADE).
    op.execute("DELETE FROM users WHERE email IS NULL")
    op.drop_constraint(op.f('uq_users_username'), 'users', type_='unique')
    op.alter_column('users', 'email',
               existing_type=sa.VARCHAR(length=254),
               nullable=False)
    op.drop_column('users', 'username')
