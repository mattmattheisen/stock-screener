"""Prospective V1-vs-V2 shadow comparison records.

This module has no persistence side effects. It defines the exact point-in-time
record that a future shadow collector should store after V1 and V2 evaluate the
same pre-fetched StockData snapshot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .base_screener import ScreenerResult
from .criteria.canslim_v2 import METHODOLOGY_VERSION


@dataclass(frozen=True)
class CANSLIMV2ShadowRecord:
    """One point-in-time V1/V2 comparison for a symbol."""

    symbol: str
    as_of_date: str | None
    run_ref: str | None
    methodology_version: str
    v1_score: float
    v1_passes: bool
    v1_rating: str
    v2_stock_score: float
    v2_stock_passes: bool
    v2_market_passes: bool
    v2_actionable: bool
    v2_rating: str
    v2_status: str
    market_exposure_score: float | None
    market_stance: str | None
    score_delta_v2_minus_v1: float
    action_disagreement: bool
    criteria: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly payload suitable for future persistence."""

        return asdict(self)


def build_shadow_record(
    *,
    symbol: str,
    v1_result: ScreenerResult,
    v2_result: ScreenerResult,
    as_of_date: str | None = None,
    run_ref: str | None = None,
) -> CANSLIMV2ShadowRecord:
    """Build a point-in-time comparison from same-snapshot V1 and V2 results.

    This function intentionally accepts completed results rather than fetching
    data itself. The caller is responsible for ensuring V1 and V2 received the
    same pre-fetched StockData and market snapshot.
    """

    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    if v1_result.screener_name != "canslim":
        raise ValueError("v1_result must come from the legacy canslim scanner")
    if v2_result.screener_name != "canslim_v2":
        raise ValueError("v2_result must come from canslim_v2")

    details = v2_result.details if isinstance(v2_result.details, dict) else {}
    full_analysis = details.get("full_analysis")
    if not isinstance(full_analysis, dict):
        raise ValueError("v2_result is missing full_analysis shadow evidence")
    criteria = full_analysis.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set("CANSLIM"):
        raise ValueError("v2_result must contain all seven CAN SLIM criteria")

    market = details.get("market") if isinstance(details.get("market"), dict) else {}
    market_metrics = market.get("metrics") if isinstance(market.get("metrics"), dict) else {}
    v2_stock_passes = bool(details.get("stock_passes", False))
    v2_market_passes = bool(details.get("market_passes", False))
    v2_actionable = bool(details.get("actionable", False))

    return CANSLIMV2ShadowRecord(
        symbol=normalized_symbol,
        as_of_date=as_of_date,
        run_ref=run_ref,
        methodology_version=str(
            details.get("methodology_version") or METHODOLOGY_VERSION
        ),
        v1_score=round(float(v1_result.score), 4),
        v1_passes=bool(v1_result.passes),
        v1_rating=str(v1_result.rating),
        v2_stock_score=round(float(v2_result.score), 4),
        v2_stock_passes=v2_stock_passes,
        v2_market_passes=v2_market_passes,
        v2_actionable=v2_actionable,
        v2_rating=str(v2_result.rating),
        v2_status=str(details.get("status") or "unknown"),
        market_exposure_score=(
            float(market_metrics["exposure_score"])
            if market_metrics.get("exposure_score") is not None
            else None
        ),
        market_stance=(
            str(market_metrics["stance"])
            if market_metrics.get("stance") is not None
            else None
        ),
        score_delta_v2_minus_v1=round(
            float(v2_result.score) - float(v1_result.score), 4
        ),
        action_disagreement=bool(v1_result.passes) != v2_actionable,
        criteria=criteria,
    )
