"""Read-only audit of historical market-price records.

The audit reports issues; it never certifies price adjustment provenance,
infers a split from a large price change, or enables trading.
No external libraries or network calls are required.
"""
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class PriceAuditRow:
    day: date
    raw_close: float
    adj_close: float | None
    volume: int
    split_ratio: float | None = None


@dataclass(frozen=True)
class AuditFinding:
    code: str
    day: date | None
    detail: str


def audit_prices(rows: Iterable[PriceAuditRow], *, as_of: date,
                 expected_last_session: date) -> list[AuditFinding]:
    """Non-certifying diagnostics for a cached symbol's price lookback."""
    values = list(rows)
    findings: list[AuditFinding] = []
    if not values:
        return [AuditFinding("NO_DATA", None, "No price rows")]
    if expected_last_session > as_of:
        findings.append(AuditFinding("INVALID_CUTOFF", None,
                      "Expected session is later than research as-of date"))
    seen: set[date] = set()
    ordered = sorted(values, key=lambda x: x.day)
    for row in ordered:
        if row.day in seen:
            findings.append(AuditFinding("DUPLICATE_DATE", row.day, "Repeated session"))
        seen.add(row.day)
        if row.day > as_of:
            findings.append(AuditFinding("FUTURE_BAR", row.day, "Look-ahead risk"))
        if (not isfinite(row.raw_close)) or row.raw_close <= 0:
            findings.append(AuditFinding("INVALID_RAW_CLOSE", row.day,
                                          "Raw closing price is invalid"))
        if row.adj_close is None or not isfinite(row.adj_close) or row.adj_close <= 0:
            findings.append(AuditFinding("MISSING_ADJUSTED_CLOSE", row.day,
                      "Cannot rely on raw-close fallback or invalid adjusted close"))
        if row.volume < 0:
            findings.append(AuditFinding("INVALID_VOLUME", row.day, "Negative volume"))
        if row.split_ratio is not None:
            if not isfinite(row.split_ratio) or row.split_ratio <= 0:
                findings.append(AuditFinding("INVALID_SPLIT_RATIO", row.day, "Invalid split event"))
            elif row.split_ratio != 1:
                findings.append(AuditFinding("SPLIT_WINDOW", row.day,
                        "Split requires confirmed adjusted volume, OHLC and entry normalization"))
    eligible = [r.day for r in ordered if r.day <= as_of]
    if not eligible or max(eligible) != expected_last_session:
        findings.append(AuditFinding("STALE_OR_MISSING_EXPECTED_BAR", expected_last_session,
                                      "No observation for expected completed session"))
    # A large change is a diagnostic only: earnings gaps are not necessarily splits.
    for previous, current in zip(ordered, ordered[1:]):
        if (previous.raw_close > 0 and current.raw_close > 0
                and isfinite(previous.raw_close) and isfinite(current.raw_close)
                and abs(current.raw_close / previous.raw_close - 1) > .35):
            findings.append(AuditFinding("LARGE_RAW_PRICE_DISCONTINUITY", current.day,
                    "Investigate split, earnings gap, ticker change or bad print"))
    findings.append(AuditFinding("PROVENANCE_NOT_CERTIFIED", None,
          "Numerical audit cannot prove whether Adj Close was independently adjusted; "
          "verify provider source metadata and corporate-action history separately"))
    return findings
