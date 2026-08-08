from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from app.models.market_breadth import MarketBreadth


def test_market_breadth_has_nullable_eligibility_signature():
    column = MarketBreadth.__table__.c.eligibility_signature

    assert column.type.length == 64
    assert column.nullable is True


def test_breadth_eligibility_migration_follows_current_head():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20260808_0027_add_breadth_eligibility_signature.py"
    )
    spec = spec_from_file_location("breadth_eligibility_migration", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.revision == "20260808_0027"
    assert module.down_revision == "20260805_0026"
