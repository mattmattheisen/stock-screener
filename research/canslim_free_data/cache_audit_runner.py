"""Read-only, fail-closed diagnostics against the existing PriceCacheService.

Unlike a synthetic provenance receipt, this reads the actual cached frame.
This report NEVER attests that Adj Close or split-adjusted volumes are correct.
It deliberately cannot produce executable/production exit signals.
"""
from dataclasses import dataclass
from datetime import date, datetime
from math import nan
from typing import Any

from price_audit import PriceAuditRow, audit_prices


@dataclass(frozen=True)
class CacheDiagnostic:
    symbol: str
    as_of: date
    expected_last_session: date
    last_seen_session: date | None
    row_count: int
    findings: tuple[str, ...]
    source: str
    data_certified: bool = False


def _day(index: Any) -> date:
    if isinstance(index, datetime):
        return index.date()
    if isinstance(index, date):
        return index
    raise ValueError("Index has no explicit trading date")


def _finite_float(value: Any) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return nan


def inspect_cached_prices(
    cache: Any, *, symbol: str, as_of: date,
    expected_last_session: date, source: str = "stock_screener_price_cache",
) -> CacheDiagnostic:
    """Call the existing cache-only API; no remote provider fetch is attempted.

    'data_certified' is always False because neither cached column names nor
    optional user-provided verification text proves adjustment provenance.
    """
    if expected_last_session > as_of:
        raise ValueError("Expected session cannot be after research as_of")
    if not symbol or not source:
        raise ValueError("Symbol and source are required")
    frame = cache.get_cached_only(symbol, period="1y")
    if frame is None or frame.empty:
        return CacheDiagnostic(symbol, as_of, expected_last_session, None, 0,
                               ("NO_DATA", "PROVENANCE_NOT_CERTIFIED"), source)
    columns = set(frame.columns)
    if not {"Close", "Volume"}.issubset(columns):
        return CacheDiagnostic(symbol, as_of, expected_last_session, None, 0,
                               ("MISSING_RAW_OHLCV", "PROVENANCE_NOT_CERTIFIED"), source)
    explicit_adjusted = "Adj Close" in columns
    records = []
    for idx, data in frame.iterrows():
        day = _day(idx)
        raw_close = _finite_float(data["Close"])
        adjusted_close = (_finite_float(data["Adj Close"])
                          if explicit_adjusted else None)
        volume = _finite_float(data["Volume"])
        # invalid volume is flagged as negative; do not silently zero-fill it
        valid_volume = int(volume) if volume >= 0 and volume.is_integer() else -1
        records.append(PriceAuditRow(day, raw_close, adjusted_close, valid_volume))
    findings = [f.code for f in audit_prices(
        records, as_of=as_of, expected_last_session=expected_last_session
    )]
    if not explicit_adjusted:
        findings.append("EXPLICIT_ADJUSTED_COLUMN_ABSENT")
    if any(r.adj_close == r.raw_close for r in records):
        findings.append("EQUAL_RAW_ADJUSTED_REQUIRES_SOURCE_VERIFICATION")
    # The existing cache lacks trustworthy, row-level split/event provenance.
    findings.append("CORPORATE_ACTION_SOURCE_UNVERIFIED")
    findings.append("HISTORICAL_AS_OF_SNAPSHOT_UNVERIFIED")
    eligible = [r.day for r in records if r.day <= as_of]
    return CacheDiagnostic(
        symbol, as_of, expected_last_session, max(eligible) if eligible else None,
        len(records), tuple(sorted(set(findings))), source,
    )
