"""Add canonical breadth contributor snapshots.

Revision ID: 20260829_0033
Revises: 20260825_0032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260829_0033"
down_revision = "20260825_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_breadth_contributor_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("calculation_revision", sa.Integer(), nullable=False),
        sa.Column("schema_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["date", "market"],
            ["market_breadth.date", "market_breadth.market"],
            name="fk_breadth_contributor_snapshot_aggregate",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "market",
            "date",
            name="uq_breadth_contributor_snapshot_market_date",
        ),
    )
    op.create_index(
        "ix_breadth_contributor_snapshot_market_date",
        "market_breadth_contributor_snapshots",
        ["market", "date"],
    )
    op.create_table(
        "market_breadth_contributors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("ibd_industry_group", sa.String(length=255), nullable=False),
        sa.Column("daily_change_pct", sa.Float(), nullable=True),
        sa.Column("signals_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["market_breadth_contributor_snapshots.id"],
            name="fk_breadth_contributor_snapshot",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "symbol",
            name="uq_breadth_contributor_snapshot_symbol",
        ),
    )
    op.create_index(
        "ix_breadth_contributor_snapshot_id",
        "market_breadth_contributors",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_breadth_contributor_snapshot_id",
        table_name="market_breadth_contributors",
    )
    op.drop_table("market_breadth_contributors")
    op.drop_index(
        "ix_breadth_contributor_snapshot_market_date",
        table_name="market_breadth_contributor_snapshots",
    )
    op.drop_table("market_breadth_contributor_snapshots")
