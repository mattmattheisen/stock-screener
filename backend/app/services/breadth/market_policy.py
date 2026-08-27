"""Fixed local-market eligibility policies for StockBee breadth signals."""

from __future__ import annotations

from .types import BreadthMarketPolicy


BREADTH_MARKET_POLICIES: dict[str, BreadthMarketPolicy] = {
    "US": BreadthMarketPolicy("US", "USD", 250_000, 100_000, 5.00),
    "CA": BreadthMarketPolicy("CA", "CAD", 5_000, 5_000, 0.30),
    "DE": BreadthMarketPolicy("DE", "EUR", 5_000, 300, 8.00),
    "HK": BreadthMarketPolicy("HK", "HKD", 20_000, 150_000, 0.20),
    "IN": BreadthMarketPolicy("IN", "INR", 100_000, 15_000, 15.00),
    "JP": BreadthMarketPolicy("JP", "JPY", 8_000_000, 50_000, 500.00),
    "KR": BreadthMarketPolicy("KR", "KRW", 100_000_000, 50_000, 2_000.00),
    "TW": BreadthMarketPolicy("TW", "TWD", 3_500_000, 400_000, 20.00),
    "CN": BreadthMarketPolicy("CN", "CNY", 50_000_000, 10_000_000, 5.00),
}


def get_breadth_market_policy(market: str) -> BreadthMarketPolicy:
    """Return the canonical breadth policy or fail before calculation starts."""

    market_code = str(market or "").strip().upper()
    try:
        return BREADTH_MARKET_POLICIES[market_code]
    except KeyError as exc:
        rendered_market = market_code or "<missing>"
        raise ValueError(
            f"Breadth is not supported for market {rendered_market}"
        ) from exc
