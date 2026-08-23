"""Upgrade/downgrade proof for backend-owned scan metadata."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260823_0029_add_scan_metadata.py"
)


def _load_migration():
    assert MIGRATION_PATH.exists(), "scan metadata migration is missing"
    spec = importlib.util.spec_from_file_location(MIGRATION_PATH.stem, MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(module, connection, operation: str) -> None:
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, operation)()


def test_upgrade_moves_only_recognized_marker_and_downgrade_restores_it():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    scans = sa.Table(
        "scans",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("criteria", sa.JSON, nullable=True),
    )
    metadata.create_all(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        connection.execute(
            scans.insert().values(
                id=1,
                criteria={
                    "custom_filters": {"price_min": 10},
                    "materialization_versions": {
                        "opportunity_state": 1,
                        "other_feature": 2,
                    },
                },
            )
        )
        _run(migration, connection, "upgrade")
        upgraded = connection.execute(
            sa.text("SELECT criteria, metadata_json FROM scans WHERE id = 1")
        ).mappings().one()

        assert migration.decode_json(upgraded["criteria"]) == {
            "custom_filters": {"price_min": 10},
            "materialization_versions": {"other_feature": 2},
        }
        assert migration.decode_json(upgraded["metadata_json"]) == {
            "materialization_versions": {"opportunity_state": 1}
        }

        _run(migration, connection, "downgrade")
        restored = connection.execute(
            sa.text("SELECT criteria FROM scans WHERE id = 1")
        ).scalar_one()

    assert migration.decode_json(restored) == {
        "custom_filters": {"price_min": 10},
        "materialization_versions": {
            "other_feature": 2,
            "opportunity_state": 1,
        },
    }
