"""Shared coverage gates for static market publication paths."""

from __future__ import annotations

import math

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
    """Return the static breadth history's stock-scan coverage floor."""
    return market_current_price_min_coverage(market)


def static_breadth_minimum_validated_scan_count(
    supported_symbol_count: int,
    *,
    market: str,
) -> int:
    """Return the minimum breadth rows that must scan valid symbols."""
    if supported_symbol_count <= 0:
        return 0
    return max(
        1,
        math.ceil(
            supported_symbol_count * static_breadth_history_min_coverage(market)
        ),
    )
