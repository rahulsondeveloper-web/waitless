"""Waiter in charge of each table (one waiter per table, many tables per waiter)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-19 14:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = '0016'
down_revision: str | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('restaurant_tables', sa.Column('waiter_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f('fk_restaurant_tables_waiter_user_id_users'),
        'restaurant_tables',
        'users',
        ['waiter_user_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(op.f('ix_restaurant_tables_waiter_user_id'), 'restaurant_tables', ['waiter_user_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_restaurant_tables_waiter_user_id'), table_name='restaurant_tables')
    op.drop_constraint(op.f('fk_restaurant_tables_waiter_user_id_users'), 'restaurant_tables', type_='foreignkey')
    op.drop_column('restaurant_tables', 'waiter_user_id')
