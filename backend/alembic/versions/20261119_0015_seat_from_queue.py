"""Seat from the queue page: a "seat" waiter alert with a note (e.g. "add 2 chairs")

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-19 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('service_requests', sa.Column('note', sa.String(length=120), nullable=True))
    op.drop_constraint(op.f('ck_service_requests_kind'), 'service_requests', type_='check')
    op.create_check_constraint(
        op.f('ck_service_requests_kind'), 'service_requests', "kind IN ('water', 'tissue', 'bill', 'help', 'seat')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM service_requests WHERE kind = 'seat'")
    op.drop_constraint(op.f('ck_service_requests_kind'), 'service_requests', type_='check')
    op.create_check_constraint(
        op.f('ck_service_requests_kind'), 'service_requests', "kind IN ('water', 'tissue', 'bill', 'help')"
    )
    op.drop_column('service_requests', 'note')
