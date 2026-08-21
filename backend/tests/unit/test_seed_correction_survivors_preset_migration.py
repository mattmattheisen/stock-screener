"""Behavior tests for the correction-survivors preset seed migration."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.services.preset_screens import PRESET_SCREENS


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260821_0028_seed_correction_survivors_preset.py"
)


def _load_migration():
    assert MIGRATION_PATH.exists(), "correction-survivors migration is missing"
    spec = importlib.util.spec_from_file_location(MIGRATION_PATH.stem, MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_filter_presets_table(engine: sa.Engine) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "filter_presets",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("filters", sa.Text, nullable=False),
        sa.Column("sort_by", sa.String(50), nullable=False),
        sa.Column("sort_order", sa.String(10), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
    )
    metadata.create_all(engine)


def _run(module, connection, operation: str) -> None:
    context = MigrationContext.configure(connection)
    module.op = Operations(context)
    getattr(module, operation)()


def _insert_user_preset(connection, *, name: str, position: int = 0) -> int:
    result = connection.execute(
        sa.text(
            "INSERT INTO filter_presets "
            "(name, description, filters, sort_by, sort_order, position) "
            "VALUES (:name, 'user copy', :filters, 'composite_score', 'desc', :position)"
        ),
        {"name": name, "filters": json.dumps({"customized": True}), "position": position},
    )
    return int(result.lastrowid)


def test_live_seed_matches_static_semantics():
    migration = _load_migration()
    static = next(
        item for item in PRESET_SCREENS if item["id"] == "correction_survivors"
    )
    live = migration.CORRECTION_SURVIVORS_PRESET

    assert live["name"] == static["name"] == "Correction Survivors"
    assert live["description"].rstrip(".") == static["description"].rstrip(".")
    assert live["filter_overrides"] == static["filters"]
    assert (live["sort_by"], live["sort_order"]) == (
        static["sort_by"],
        static["sort_order"],
    )


def test_upgrade_skips_same_name_user_preset_and_audits_nothing():
    engine = sa.create_engine("sqlite:///:memory:")
    _make_filter_presets_table(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        user_id = _insert_user_preset(connection, name="Correction Survivors")
        _run(migration, connection, "upgrade")
        row = connection.execute(
            sa.text(
                "SELECT id, description, filters FROM filter_presets "
                "WHERE name = 'Correction Survivors'"
            )
        ).one()
        audited_ids = connection.execute(
            sa.text(
                f"SELECT filter_preset_id FROM {migration._AUDIT_TABLE_NAME}"
            )
        ).scalars().all()
        _run(migration, connection, "downgrade")
        remaining = connection.execute(
            sa.text(
                "SELECT id, description, filters FROM filter_presets "
                "WHERE name = 'Correction Survivors'"
            )
        ).one()

    engine.dispose()

    assert row == (user_id, "user copy", json.dumps({"customized": True}))
    assert audited_ids == []
    assert remaining == row


def test_upgrade_audits_only_the_row_it_inserts():
    engine = sa.create_engine("sqlite:///:memory:")
    _make_filter_presets_table(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        user_id = _insert_user_preset(connection, name="User Custom")
        _run(migration, connection, "upgrade")
        seeded = connection.execute(
            sa.text(
                "SELECT id, filters, sort_by, sort_order FROM filter_presets "
                "WHERE name = 'Correction Survivors'"
            )
        ).one()
        audited_ids = connection.execute(
            sa.text(
                f"SELECT filter_preset_id FROM {migration._AUDIT_TABLE_NAME}"
            )
        ).scalars().all()

    engine.dispose()

    assert audited_ids == [seeded.id]
    assert user_id not in audited_ids
    filters = json.loads(seeded.filters)
    assert filters["correctionSurvivor"] is True
    assert filters["seRsLineBlueDot"] is None
    assert filters["rsLineBlueDotRecent"] is None
    assert filters["ibdGroupRank"] == {"min": None, "max": None}
    assert (seeded.sort_by, seeded.sort_order) == ("resilience_score", "desc")


def test_downgrade_removes_an_unchanged_migration_owned_row():
    engine = sa.create_engine("sqlite:///:memory:")
    _make_filter_presets_table(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        user_id = _insert_user_preset(connection, name="User Custom")
        _run(migration, connection, "upgrade")
        _run(migration, connection, "downgrade")
        remaining = connection.execute(
            sa.text("SELECT id, name FROM filter_presets ORDER BY id")
        ).all()

    engine.dispose()

    assert remaining == [(user_id, "User Custom")]


def test_downgrade_preserves_a_user_edited_seeded_row():
    engine = sa.create_engine("sqlite:///:memory:")
    _make_filter_presets_table(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        _run(migration, connection, "upgrade")
        connection.execute(
            sa.text(
                "UPDATE filter_presets SET description = 'My edited survivor screen' "
                "WHERE name = 'Correction Survivors'"
            )
        )
        _run(migration, connection, "downgrade")
        remaining = connection.execute(
            sa.text("SELECT name, description FROM filter_presets")
        ).all()

    engine.dispose()

    assert remaining == [("Correction Survivors", "My edited survivor screen")]
