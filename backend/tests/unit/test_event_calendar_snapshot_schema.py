from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from app.models.stock import StockFundamental


def _migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20260823_0030_add_event_calendar_snapshot.py"
    )
    spec = spec_from_file_location(path.stem, path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_fundamentals_model_has_nullable_event_calendar_snapshot():
    table = StockFundamental.__table__.c

    assert table.next_earnings_date.nullable is True
    assert table.event_calendar_as_of_date.nullable is True


def test_event_calendar_snapshot_migration_extends_current_head():
    migration = _migration_module()

    assert migration.revision == "20260823_0030"
    assert migration.down_revision == "20260823_0029"
