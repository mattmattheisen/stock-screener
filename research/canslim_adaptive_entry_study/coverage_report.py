"""Read-only historical coverage report, invoked explicitly from backend environment.

Run from repository root:
  PYTHONPATH=backend:. python -m research.canslim_adaptive_entry_study.coverage_report

Does not update DB, fetch external data, or infer publication timestamps.
Outputs aggregate coverage only, never account or client data.
"""
from __future__ import annotations

import json
from sqlalchemy import create_engine, text
from app.config import settings


QUERIES = {
    "price_history": """
        SELECT count(*) AS rows, count(DISTINCT symbol) AS symbols,
               min(date) AS earliest, max(date) AS latest,
               count(*) FILTER (WHERE high IS NULL OR close IS NULL OR volume IS NULL) AS missing_ohlcv,
               count(*) FILTER (WHERE adj_close IS NULL) AS missing_adjusted_close
        FROM stock_prices
    """,
    "fundamentals_current_snapshot": """
        SELECT count(*) AS rows, count(DISTINCT symbol) AS symbols,
               min(data_source_timestamp) AS earliest_source_timestamp,
               max(data_source_timestamp) AS latest_source_timestamp,
               count(*) FILTER (WHERE eps_growth_quarterly IS NULL) AS missing_quarterly_eps,
               count(*) FILTER (WHERE eps_growth_annual IS NULL) AS missing_annual_eps,
               count(*) FILTER (WHERE institutional_ownership IS NULL) AS missing_institutional_ownership
        FROM stock_fundamentals
    """,
    "daily_feature_runs": """
        SELECT count(*) AS rows, count(DISTINCT as_of_date) AS distinct_dates,
               min(as_of_date) AS earliest, max(as_of_date) AS latest,
               count(*) FILTER (WHERE published_at IS NULL) AS never_published
        FROM feature_runs
    """,
    "daily_feature_snapshots": """
        SELECT count(*) AS rows, count(DISTINCT symbol) AS symbols,
               count(DISTINCT as_of_date) AS distinct_dates,
               min(as_of_date) AS earliest, max(as_of_date) AS latest,
               count(*) FILTER (WHERE details_json IS NULL) AS missing_details
        FROM stock_feature_daily
    """,
}


def collect(connection) -> dict:
    """Accept a read-only SQLAlchemy connection; missing tables are reported."""
    report = {}
    for name, query in QUERIES.items():
        try:
            row = connection.execute(text(query)).mappings().one()
            report[name] = {key: str(value) if hasattr(value, "isoformat") else value for key, value in row.items()}
        except Exception as exc:
            # Do not expose DSNs or credentials from database exception messages.
            report[name] = {"status": "UNAVAILABLE", "error_type": type(exc).__name__}
    report["historical_ibd_rs"] = {"status": "UNVERIFIED", "reason": "No verified licensed historical IBD RS archive identified"}
    report["historical_fundamental_asof"] = {"status": "UNVERIFIED", "reason": "Current fundamentals rows do not establish historical as-of observations"}
    report["delisted_universe"] = {"status": "UNVERIFIED", "reason": "Survivorship-free security master not established"}
    return report


def main() -> None:
    # Explicit connection only; no data writes. Set database user to SELECT-only.
    from app.database import engine
    with engine.connect() as conn:
        print(json.dumps(collect(conn), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
