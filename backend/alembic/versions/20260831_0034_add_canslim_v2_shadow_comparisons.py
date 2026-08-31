"""Add immutable CAN SLIM V1-vs-V2 shadow comparisons.

Revision ID: 20260831_0034
Revises: 20260829_0033
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260831_0034"
down_revision = "20260829_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canslim_v2_shadow_comparisons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("run_ref", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("methodology_version", sa.String(length=64), nullable=False),
        sa.Column("v1_score", sa.Float(), nullable=False),
        sa.Column("v1_passes", sa.Boolean(), nullable=False),
        sa.Column("v1_rating", sa.String(length=32), nullable=False),
        sa.Column("v2_stock_score", sa.Float(), nullable=False),
        sa.Column("v2_stock_passes", sa.Boolean(), nullable=False),
        sa.Column("v2_market_passes", sa.Boolean(), nullable=False),
        sa.Column("v2_actionable", sa.Boolean(), nullable=False),
        sa.Column("v2_rating", sa.String(length=32), nullable=False),
        sa.Column("v2_status", sa.String(length=64), nullable=False),
        sa.Column("market_exposure_score", sa.Float(), nullable=True),
        sa.Column("market_stance", sa.String(length=64), nullable=True),
        sa.Column("score_delta_v2_minus_v1", sa.Float(), nullable=False),
        sa.Column("action_disagreement", sa.Boolean(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "as_of_date",
            "run_ref",
            "symbol",
            "methodology_version",
            name="uq_canslim_v2_shadow_identity",
        ),
    )
    op.create_index(
        "ix_canslim_v2_shadow_asof_symbol",
        "canslim_v2_shadow_comparisons",
        ["as_of_date", "symbol"],
    )
    op.create_index(
        "ix_canslim_v2_shadow_methodology",
        "canslim_v2_shadow_comparisons",
        ["methodology_version"],
    )
    op.create_index(
        "ix_canslim_v2_shadow_disagreement",
        "canslim_v2_shadow_comparisons",
        ["action_disagreement", "as_of_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canslim_v2_shadow_disagreement",
        table_name="canslim_v2_shadow_comparisons",
    )
    op.drop_index(
        "ix_canslim_v2_shadow_methodology",
        table_name="canslim_v2_shadow_comparisons",
    )
    op.drop_index(
        "ix_canslim_v2_shadow_asof_symbol",
        table_name="canslim_v2_shadow_comparisons",
    )
    op.drop_table("canslim_v2_shadow_comparisons")
