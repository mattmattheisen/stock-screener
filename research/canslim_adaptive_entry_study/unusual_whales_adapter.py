"""Fail-closed adapter for Unusual Whales daily ticker day-state records.

UW returns daily OHLC and options flow, but its daily endpoint does not
currently expose underlying share volume. Never substitute call/put volume.
This adapter produces research-only price observations and a completeness report.
"""
from __future__ import annotations

from datetime import date
import math


def adapt_daily_rows(rows, symbol: str):
    """Return chronological normalized rows and a conservative quality report."""
    if not symbol or not symbol.strip():
        raise ValueError("Symbol required")
    symbol = symbol.strip().upper()
    seen = set()
    bars = []
    for i, item in enumerate(rows):
        if item.get("ticker", "").upper() != symbol:
            raise ValueError(f"row {i}: ticker mismatch")
        day = date.fromisoformat(item["date"]).isoformat()
        if day in seen:
            raise ValueError(f"row {i}: duplicate date")
        seen.add(day)
        vals = [float(item[key]) for key in ("open", "high", "low", "close")]
        if any(not math.isfinite(v) or v <= 0 for v in vals):
            raise ValueError(f"row {i}: invalid OHLC")
        op, hi, lo, cl = vals
        if lo > min(op, cl) or hi < max(op, cl):
            raise ValueError(f"row {i}: inconsistent OHLC")
        bars.append({"symbol": symbol, "date": day, "open": op, "high": hi,
                     "low": lo, "close": cl, "share_volume": None,
                     "source": "unusual_whales_ticker_ohlc_daily",
                     "adjustment_basis": "unverified"})
    bars.sort(key=lambda b: b["date"])
    report = {
        "symbol": symbol, "rows": len(bars),
        "earliest": bars[0]["date"] if bars else None,
        "latest": bars[-1]["date"] if bars else None,
        "daily_ohlc_available": bool(bars),
        "share_volume_available": False,
        "adjustment_basis_verified": False,
        "historical_ibd_rs_available": False,
        "full_canslim_backtest_ready": False,
        "notes": [
            "Underlying share volume absent from this UW endpoint",
            "Options contract volume is not stock share volume",
            "Corporate-action adjustment policy unverified",
            "No point-in-time fundamentals or proprietary IBD RS",
        ],
    }
    return bars, report
