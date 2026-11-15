"""Guarded bridge from existing PriceCacheService to the offline CAN SLIM contract.

This module makes no external request; it only reads existing screener cache.
A production pipeline MUST first independently reconcile corporate actions,
price-adjustment provenance and close-of-session freshness.
"""
from datetime import date, datetime
from typing import Any

from data_contract import MarketObservation, Signal, evaluate_history


class UnverifiedPriceData(ValueError):
    """Cannot certify a signal with unknown data semantics."""


def _date(index: Any) -> date:
    if isinstance(index, datetime):
        return index.date()
    if isinstance(index, date):
        return index
    raise UnverifiedPriceData("Cache index must contain date/datetime objects")


def from_cached_frame(
    frame: Any, *, symbol: str, as_of: date, last_complete_session: date,
    source: str, adjustment_provenance_verified: bool,
    corporate_action_window_verified: bool,
) -> Signal:
    """Read cached frame with explicit upstream attestations.

    Requires a column 'Adj Close' supplied with independently audited
    adjustment semantics. Do not infer adjustment from 'Close' or equality.
    'Volume' is normally raw; if splits occurred within the lookback, the
    corporate-action verification must include volume comparability.
    """
    if not source or not adjustment_provenance_verified or not corporate_action_window_verified:
        raise UnverifiedPriceData("Price adjustment, source, or corporate actions unverified")
    if last_complete_session > as_of:
        raise UnverifiedPriceData("Completed-session date is after requested as_of")
    if frame is None or frame.empty:
        raise UnverifiedPriceData("No cached market observations")
    required = {"Adj Close", "Volume"}
    if not required.issubset(set(frame.columns)):
        raise UnverifiedPriceData("Missing explicit Adj Close or Volume; no raw-close fallback")
    obs = []
    for idx, row in frame.iterrows():
        day = _date(idx)
        if day > last_complete_session or day > as_of:
            continue
        value, volume = row["Adj Close"], row["Volume"]
        if value is None or volume is None:
            raise UnverifiedPriceData("Incomplete adjusted price or volume")
        try:
            price = float(value)
            volume_float = float(volume)
        except (ValueError, TypeError):
            raise UnverifiedPriceData("Malformed price or volume") from None
        if not volume_float.is_integer():
            raise UnverifiedPriceData("Fractional volume")
        obs.append(MarketObservation(symbol, day, price, int(volume_float), source, True, True))
    if not obs:
        raise UnverifiedPriceData("No completed bars at or before cutoff")
    signal = evaluate_history(obs, as_of)
    if signal.as_of != last_complete_session:
        raise UnverifiedPriceData("Stale cache: latest bar not the expected complete session")
    return signal


def read_existing_cache(
    price_cache: Any, *, symbol: str, as_of: date, last_complete_session: date,
    source: str, adjustment_provenance_verified: bool = False,
    corporate_action_window_verified: bool = False,
) -> Signal:
    """Reuse PriceCacheService cache-only read; never auto-fetch network data.

    The approval flags default to False on purpose. A caller must supply
    evidence-based verification; setting these True blindly is prohibited.
    """
    if not adjustment_provenance_verified or not corporate_action_window_verified:
        raise UnverifiedPriceData("Data requires upstream provenance verification")
    frame = price_cache.get_cached_only(symbol, period="1y")
    return from_cached_frame(
        frame, symbol=symbol, as_of=as_of,
        last_complete_session=last_complete_session, source=source,
        adjustment_provenance_verified=adjustment_provenance_verified,
        corporate_action_window_verified=corporate_action_window_verified,
    )
