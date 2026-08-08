"""Add date-specific breadth eligibility signature."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "20260808_0027"
down_revision = "20260805_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_breadth",
        sa.Column("eligibility_signature", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_breadth", "eligibility_signature")
