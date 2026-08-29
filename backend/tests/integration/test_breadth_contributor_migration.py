"""Upgrade/downgrade proof for breadth contributor snapshot storage."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260829_0033_add_breadth_contributor_snapshots.py"
)


def _load_migration():
    if not MIGRATION_PATH.is_file():
        pytest.fail(f"breadth contributor migration is missing: {MIGRATION_PATH}")
    spec = importlib.util.spec_from_file_location(
        "breadth_contributor_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_revision(engine, operation: str) -> None:
    module = _load_migration()
    with engine.begin() as connection:
        alembic_operations = Operations(MigrationContext.configure(connection))
        original_op = module.op
        module.op = alembic_operations
        try:
            getattr(module, operation)()
        finally:
            module.op = original_op


def _create_current_breadth_schema(engine) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "market_breadth",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.UniqueConstraint("date", "market", name="uix_breadth_date_market"),
    )
    metadata.create_all(engine)


def test_contributor_migration_creates_and_removes_parent_child_contract(tmp_path):
    """Catches missing identity, cascade, JSON, or downgrade behavior."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'contributors.sqlite'}")
    _create_current_breadth_schema(engine)

    _run_revision(engine, "upgrade")
    inspector = sa.inspect(engine)
    assert {
        "market_breadth_contributor_snapshots",
        "market_breadth_contributors",
    }.issubset(inspector.get_table_names())
    parent_columns = {
        column["name"]: column
        for column in inspector.get_columns("market_breadth_contributor_snapshots")
    }
    child_columns = {
        column["name"]: column
        for column in inspector.get_columns("market_breadth_contributors")
    }
    assert parent_columns["schema_id"]["nullable"] is False
    assert parent_columns["calculation_revision"]["nullable"] is False
    assert isinstance(child_columns["signals_json"]["type"], sa.JSON)
    assert any(
        item["name"] == "uq_breadth_contributor_snapshot_market_date"
        for item in inspector.get_unique_constraints(
            "market_breadth_contributor_snapshots"
        )
    )
    assert any(
        item["name"] == "uq_breadth_contributor_snapshot_symbol"
        for item in inspector.get_unique_constraints("market_breadth_contributors")
    )

    _run_revision(engine, "downgrade")
    assert {
        "market_breadth_contributor_snapshots",
        "market_breadth_contributors",
    }.isdisjoint(sa.inspect(engine).get_table_names())
    assert "market_breadth" in sa.inspect(engine).get_table_names()
    engine.dispose()
