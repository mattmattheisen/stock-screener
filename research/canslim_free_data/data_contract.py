"""Provider-neutral CAN SLIM research data contract.

Offline, standard-library-only module. No paid API or trade execution.
The screener's existing providers can be adapted to MarketObservation later.
"""
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Optional, Sequence

@dataclass(frozen=True)
class MarketObservation:
    symbol: str
    as_of: date
    close: float
    volume: int
    source: str
    adjusted: bool
    is_complete_session: bool

@dataclass(frozen=True)
class Signal:
    symbol: str
    as_of: date
    price: float
    sma21: Optional[float]
    sma50: Optional[float]
    volume_ratio20: Optional[float]
    status: str
    source: str
    limitations: tuple

def evaluate_history(rows: Sequence[MarketObservation], as_of: date) -> Signal:
    """Use only completed observations dated <= as_of, without look-ahead.

    This only evaluates moving averages and relative volume; proprietary IBD
    measures, fundamentals, splits and live alerts remain outside this module.
    """
    usable = sorted((r for r in rows if r.as_of <= as_of and r.is_complete_session),
                    key=lambda r: r.as_of)
    if not usable:
        raise ValueError("No completed session on or before as_of")
    symbol = usable[0].symbol
    if any(r.symbol != symbol for r in usable):
        raise ValueError("Mixed tickers are not allowed")
    if len(set(r.as_of for r in usable)) != len(usable):
        raise ValueError("Duplicate daily bars")
    if any(not r.source or not r.adjusted or not isfinite(r.close) or r.close <= 0 or r.volume < 0
           for r in usable):
        raise ValueError("Missing source, non-adjusted, or invalid daily observations")
    closes = [r.close for r in usable]
    ma21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else None
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    # Historical average excludes current session; protects against denominator leakage.
    base = usable[-21:-1]
    volume_ratio = usable[-1].volume / (sum(r.volume for r in base) / 20) if len(base) == 20 and sum(r.volume for r in base) > 0 else None
    latest = usable[-1]
    limitations = ["IBD RS and Acc/Dis unavailable", "Not a complete Exit Ledger assessment"]
    if ma21 is None or ma50 is None or volume_ratio is None:
        limitations.append("Insufficient history for 21/50-day and volume signals")
        state = "INSUFFICIENT DATA"
    elif latest.close < ma50 and volume_ratio >= 1.5:
        state = "REVIEW: below 50DMA on elevated volume"
    elif latest.close < ma21:
        state = "WATCH: below 21DMA"
    else:
        state = "NO NEW TECHNICAL TRIGGER"
    return Signal(symbol, latest.as_of, latest.close, ma21, ma50,
                  volume_ratio, state, latest.source, tuple(limitations))
