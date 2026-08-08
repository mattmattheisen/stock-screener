"""Shared coverage gates for static market publication paths."""

from __future__ import annotations

from app.config import settings


def market_current_price_min_coverage(market: str) -> float:
    """Return the canonical Market RS current-price coverage floor."""
    normalized = str(market or "").strip().lower()
    market_threshold = getattr(
        settings,
        f"market_rs_min_current_price_coverage_{normalized}",
        None,
    )
    if market_threshold is not None:
        return float(market_threshold)
    return float(settings.market_rs_min_current_price_coverage)


def static_daily_price_bundle_min_coverage(market: str) -> float:
    """Return the daily price bundle's current-session coverage floor."""
    return market_current_price_min_coverage(market)


def static_breadth_history_min_coverage(market: str) -> float:
    """Return the independent breadth floor for a prequalified universe."""
    del market
    return 1.0


def static_breadth_minimum_validated_scan_count(
    eligible_symbol_count: int,
    *,
    market: str,
) -> int:
    """Return the minimum breadth rows that must scan valid symbols."""
    if eligible_symbol_count <= 0:
        return 0
    return eligible_symbol_count
