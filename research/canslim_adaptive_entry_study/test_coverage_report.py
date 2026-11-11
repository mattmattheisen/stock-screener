"""Coverage report resilience tests using an isolated in-memory database."""
from sqlalchemy import create_engine, text

from research.canslim_adaptive_entry_study.coverage_report import collect


def test_missing_table_does_not_abort_other_queries():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE stock_prices (symbol TEXT, date DATE, high REAL, "
            "close REAL, volume INTEGER, adj_close REAL)"
        ))
        conn.execute(text(
            "INSERT INTO stock_prices VALUES ('XYZ', '2026-01-02', 100, 95, 500, NULL)"
        ))
        report = collect(conn)
    assert report["price_history"]["rows"] == 1
    assert report["price_symbol_depth"]["symbols"] == 1
    assert report["price_symbol_depth"]["symbols_below_253_sessions"] == 1
    assert report["price_history"]["missing_adjusted_close"] == 1
    assert report["fundamentals_current_snapshot"]["status"] == "UNAVAILABLE"
    assert report["daily_feature_runs"]["status"] == "UNAVAILABLE"
    assert report["daily_feature_snapshots"]["status"] == "UNAVAILABLE"
    assert report["historical_ibd_rs"]["status"] == "UNVERIFIED"
