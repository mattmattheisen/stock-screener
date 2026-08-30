"""Persisted breadth payloads for static exports pinned to a historical date."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.market_breadth import MarketBreadth
from app.services.breadth.query import breadth_query
from app.services.ui_snapshot_service import market_breadth_to_dict


def build_persisted_breadth_payload(
    *,
    db: Session,
    market: str,
    expected_as_of_date: date,
    snapshot_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a canonical breadth payload bounded to the static export date."""
    canonical = breadth_query(db, market=market).filter(
        MarketBreadth.date <= expected_as_of_date
    )
    current = canonical.filter(
        MarketBreadth.date == expected_as_of_date
    ).one_or_none()
    first_date_row = (
        canonical.with_entities(MarketBreadth.date)
        .order_by(MarketBreadth.date.asc())
        .first()
    )
    last_date_row = (
        canonical.with_entities(MarketBreadth.date)
        .order_by(MarketBreadth.date.desc())
        .first()
    )
    history_start = expected_as_of_date - timedelta(days=90)
    chart_start = expected_as_of_date - timedelta(days=31)
    history = (
        canonical.filter(MarketBreadth.date >= history_start)
        .order_by(MarketBreadth.date.desc())
        .all()
    )
    chart = (
        canonical.filter(MarketBreadth.date >= chart_start)
        .order_by(MarketBreadth.date.desc())
        .all()
    )
    benchmark_overlay = [
        dict(row)
        for row in snapshot_payload.get("benchmark_overlay") or ()
        if isinstance(row, Mapping)
        and row.get("date")
        and chart_start
        <= date.fromisoformat(str(row["date"]))
        <= expected_as_of_date
    ]
    return {
        **snapshot_payload,
        "current": market_breadth_to_dict(current),
        "summary": {
            "market": market.upper(),
            "latest_date": last_date_row[0] if last_date_row else None,
            "total_records": canonical.count(),
            "date_range_start": first_date_row[0] if first_date_row else None,
            "date_range_end": last_date_row[0] if last_date_row else None,
        },
        "history_90d": [market_breadth_to_dict(row) for row in history],
        "chart_data": [market_breadth_to_dict(row) for row in chart],
        "benchmark_overlay": benchmark_overlay,
        "spy_overlay": benchmark_overlay,
        "market": market.upper(),
    }
