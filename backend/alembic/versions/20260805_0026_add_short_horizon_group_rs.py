"""Add short-horizon Market RS fields for group tables."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260805_0026"
down_revision = "20260718_0025"
branch_labels = None
depends_on = None


STOCK_RS_CHECK = (
    "overall_rs BETWEEN 1 AND 99 AND rs_1d BETWEEN 1 AND 99 "
    "AND rs_1w BETWEEN 1 AND 99 AND rs_1m BETWEEN 1 AND 99 "
    "AND rs_3m BETWEEN 1 AND 99 AND rs_6m BETWEEN 1 AND 99 "
    "AND rs_9m BETWEEN 1 AND 99 AND rs_12m BETWEEN 1 AND 99"
)

LEGACY_STOCK_RS_CHECK = (
    "overall_rs BETWEEN 1 AND 99 AND rs_1m BETWEEN 1 AND 99 "
    "AND rs_3m BETWEEN 1 AND 99 AND rs_6m BETWEEN 1 AND 99 "
    "AND rs_9m BETWEEN 1 AND 99 AND rs_12m BETWEEN 1 AND 99"
)


def upgrade() -> None:
    with op.batch_alter_table("stock_rs_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column(
                "rs_1d",
                sa.SmallInteger(),
                nullable=False,
                server_default=sa.text("50"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "rs_1w",
                sa.SmallInteger(),
                nullable=False,
                server_default=sa.text("50"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "excess_return_1d",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "excess_return_1w",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.drop_constraint("ck_stock_rs_rating_range", type_="check")
        batch_op.create_check_constraint(
            "ck_stock_rs_rating_range",
            STOCK_RS_CHECK,
        )

    with op.batch_alter_table("ibd_group_ranks") as batch_op:
        batch_op.add_column(sa.Column("avg_rs_rating_1d", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("avg_rs_rating_1w", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("avg_rs_rating_6m", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ibd_group_ranks") as batch_op:
        batch_op.drop_column("avg_rs_rating_6m")
        batch_op.drop_column("avg_rs_rating_1w")
        batch_op.drop_column("avg_rs_rating_1d")

    with op.batch_alter_table("stock_rs_snapshots") as batch_op:
        batch_op.drop_constraint("ck_stock_rs_rating_range", type_="check")
        batch_op.create_check_constraint(
            "ck_stock_rs_rating_range",
            LEGACY_STOCK_RS_CHECK,
        )
        batch_op.drop_column("excess_return_1w")
        batch_op.drop_column("excess_return_1d")
        batch_op.drop_column("rs_1w")
        batch_op.drop_column("rs_1d")
