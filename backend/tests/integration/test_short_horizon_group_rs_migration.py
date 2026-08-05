"""Upgrade/downgrade proof for the short-horizon Group RS migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260805_0026_add_short_horizon_group_rs.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "short_horizon_group_rs_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_revision(engine, fn_name: str) -> None:
    module = _load_migration()
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original_op = module.op
        module.op = operations
        try:
            getattr(module, fn_name)()
        finally:
            module.op = original_op


def _create_pre_short_horizon_schema(engine) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "stock_rs_snapshots",
        metadata,
        sa.Column("run_id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("overall_rs", sa.SmallInteger, nullable=False),
        sa.Column("rs_1m", sa.SmallInteger, nullable=False),
        sa.Column("rs_3m", sa.SmallInteger, nullable=False),
        sa.Column("rs_6m", sa.SmallInteger, nullable=False),
        sa.Column("rs_9m", sa.SmallInteger, nullable=False),
        sa.Column("rs_12m", sa.SmallInteger, nullable=False),
        sa.Column("weighted_composite", sa.Float, nullable=False),
        sa.Column("excess_return_1m", sa.Float, nullable=False),
        sa.Column("excess_return_3m", sa.Float, nullable=False),
        sa.Column("excess_return_6m", sa.Float, nullable=False),
        sa.Column("excess_return_9m", sa.Float, nullable=False),
        sa.Column("excess_return_12m", sa.Float, nullable=False),
        sa.CheckConstraint(
            "overall_rs BETWEEN 1 AND 99 AND rs_1m BETWEEN 1 AND 99 "
            "AND rs_3m BETWEEN 1 AND 99 AND rs_6m BETWEEN 1 AND 99 "
            "AND rs_9m BETWEEN 1 AND 99 AND rs_12m BETWEEN 1 AND 99",
            name="ck_stock_rs_rating_range",
        ),
    )
    sa.Table(
        "ibd_group_ranks",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(8), nullable=False, default="US"),
        sa.Column("industry_group", sa.String(100), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("avg_rs_rating", sa.Float, nullable=False),
        sa.Column("avg_rs_rating_1m", sa.Float),
        sa.Column("avg_rs_rating_3m", sa.Float),
        sa.Column("median_rs_rating", sa.Float),
        sa.Column("weighted_avg_rs_rating", sa.Float),
        sa.Column("rs_std_dev", sa.Float),
        sa.Column("num_stocks", sa.Integer, default=0),
        sa.Column("num_stocks_rs_above_80", sa.Integer, default=0),
        sa.Column("top_symbol", sa.String(20)),
        sa.Column("top_rs_rating", sa.Float),
        sa.Column("rs_formula_version", sa.String(64), nullable=False),
        sa.Column("market_rs_run_id", sa.Integer),
        sa.UniqueConstraint(
            "industry_group",
            "date",
            "market",
            "rs_formula_version",
            name="uix_ibd_group_rank_market_date_formula",
        ),
    )
    metadata.create_all(engine)


def test_short_horizon_group_rs_migration_backfills_and_downgrades(tmp_path):
    database_path = tmp_path / "short-horizon-group-rs.sqlite"
    engine = sa.create_engine(f"sqlite:///{database_path}")
    _create_pre_short_horizon_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO stock_rs_snapshots (
                    run_id, symbol, overall_rs, rs_1m, rs_3m, rs_6m,
                    rs_9m, rs_12m, weighted_composite, excess_return_1m,
                    excess_return_3m, excess_return_6m, excess_return_9m,
                    excess_return_12m
                ) VALUES (
                    1, 'AAA', 70, 71, 72, 73, 74, 75, 72.5,
                    0.01, 0.02, 0.03, 0.04, 0.05
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO ibd_group_ranks (
                    market, industry_group, date, rank, avg_rs_rating,
                    avg_rs_rating_1m, avg_rs_rating_3m, num_stocks,
                    num_stocks_rs_above_80, rs_formula_version
                ) VALUES (
                    'US', 'Software', '2026-04-10', 1, 80.0,
                    78.0, 79.0, 3, 1, 'balanced-horizon-percentile-v2'
                )
                """
            )
        )

    _run_revision(engine, "upgrade")
    with engine.connect() as connection:
        stock_columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("stock_rs_snapshots")
        }
        assert {
            "rs_1d",
            "rs_1w",
            "excess_return_1d",
            "excess_return_1w",
        }.issubset(stock_columns)
        group_columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("ibd_group_ranks")
        }
        assert {
            "avg_rs_rating_1d",
            "avg_rs_rating_1w",
            "avg_rs_rating_6m",
        }.issubset(group_columns)
        row = connection.execute(
            sa.text(
                """
                SELECT rs_1d, rs_1w, excess_return_1d, excess_return_1w
                FROM stock_rs_snapshots
                WHERE run_id = 1 AND symbol = 'AAA'
                """
            )
        ).one()
        assert row == (50, 50, 0.0, 0.0)

    _run_revision(engine, "downgrade")
    with engine.connect() as connection:
        stock_columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("stock_rs_snapshots")
        }
        assert {
            "rs_1d",
            "rs_1w",
            "excess_return_1d",
            "excess_return_1w",
        }.isdisjoint(stock_columns)
        group_columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("ibd_group_ranks")
        }
        assert {
            "avg_rs_rating_1d",
            "avg_rs_rating_1w",
            "avg_rs_rating_6m",
        }.isdisjoint(group_columns)
        assert connection.execute(
            sa.text(
                """
                SELECT overall_rs, rs_1m, rs_3m, rs_6m, rs_9m, rs_12m
                FROM stock_rs_snapshots
                WHERE run_id = 1 AND symbol = 'AAA'
                """
            )
        ).one() == (70, 71, 72, 73, 74, 75)

    engine.dispose()
