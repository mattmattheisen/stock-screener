"""Persist event-calendar observations with fundamentals.

Revision ID: 20260823_0030
Revises: 20260823_0029
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260823_0030"
down_revision = "20260823_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_fundamentals",
        sa.Column("next_earnings_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "stock_fundamentals",
        sa.Column("event_calendar_as_of_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("stock_fundamentals") as batch_op:
        batch_op.drop_column("event_calendar_as_of_date")
        batch_op.drop_column("next_earnings_date")
