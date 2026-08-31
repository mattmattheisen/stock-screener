"""Adapter from existing StockData to deterministic CAN SLIM V2 inputs.

This module is intentionally unregistered. It proves that V2 can reuse the
repository's existing data pipeline while keeping extraction/calculation logic
separate from the pure scoring rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..base_screener import StockData
from .canslim_v2 import (
    CriterionResult,
    score_annual_earnings,
    score_current_earnings,
    score_institutional_sponsorship,
    score_leader,
    score_market_gate,
    score_new_highs,
    score_supply_demand,
)
from .canslim_v2_scorecard import CANSLIMV2Scorecard, build_scorecard


@dataclass(frozen=True)
class CANSLIMV2Inputs:
    """Scalar inputs consumed by the deterministic V2 criteria."""

    eps_yoy: float | None
    prior_eps_yoy: float | None
    sales_yoy: float | None
    eps_cagr: float | None
    eps_years_available: int
    eps_rating: float | None
    roe: float | None
    distance_from_52w_high_pct: float | None
    catalyst_recent: bool | None
    breakout_volume_ratio: float | None
    up_down_volume_ratio: float | None
    volume_surge_ratio: float | None
    shares_outstanding_millions: float | None
    rs_rating: float | None
    group_rank: int | None
    institutional_ownership_pct: float | None
    ownership_change_pct: float | None
    institutional_transactions_pct: float | None
    market_exposure_score: float | None


def _number(value: Any) -> float | None:
    """Best-effort finite float coercion."""

    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    if numeric == float("inf") or numeric == float("-inf"):
        return None
    return numeric


def _ownership_pct(value: Any) -> float | None:
    """Normalize institutional ownership from fraction-or-percent payloads."""

    numeric = _number(value)
    if numeric is None:
        return None
    return numeric * 100.0 if 0.0 <= numeric <= 1.0 else numeric


def _shares_millions(value: Any) -> float | None:
    """Normalize shares outstanding to millions.

    Cached fundamentals normally store raw share count. The small-value branch
    also tolerates already-normalized test/provider payloads.
    """

    numeric = _number(value)
    if numeric is None or numeric < 0:
        return None
    return numeric / 1_000_000.0 if numeric > 10_000.0 else numeric


def _chronological_series(data: StockData) -> tuple[pd.Series, pd.Series]:
    """Return chronological close/volume series from precompute or OHLCV."""

    precomputed = data.precomputed_scan_context
    if (
        precomputed is not None
        and precomputed.close_chrono is not None
        and precomputed.volume_chrono is not None
    ):
        return (
            precomputed.close_chrono.reset_index(drop=True),
            precomputed.volume_chrono.reset_index(drop=True),
        )
    return (
        data.price_data["Close"].reset_index(drop=True),
        data.price_data["Volume"].reset_index(drop=True),
    )


def calculate_up_down_volume_ratio(
    close_chrono: pd.Series,
    volume_chrono: pd.Series,
    *,
    lookback: int = 50,
) -> float | None:
    """Calculate accumulation/distribution volume using chronological prices.

    This intentionally computes price changes in chronological order. Reversing
    the series before ``diff`` flips the meaning of up/down days.
    """

    if close_chrono is None or volume_chrono is None:
        return None
    if len(close_chrono) < 2 or len(volume_chrono) < 2:
        return None

    aligned = pd.DataFrame(
        {
            "close": pd.to_numeric(close_chrono, errors="coerce"),
            "volume": pd.to_numeric(volume_chrono, errors="coerce"),
        }
    ).dropna()
    if len(aligned) < 2:
        return None

    aligned["change"] = aligned["close"].diff()
    recent = aligned.tail(lookback)
    up_volume = float(recent.loc[recent["change"] > 0, "volume"].sum())
    down_volume = float(recent.loc[recent["change"] < 0, "volume"].sum())

    if up_volume <= 0 and down_volume <= 0:
        return None
    if down_volume <= 0:
        return 10.0
    return round(min(10.0, up_volume / down_volume), 4)


def calculate_volume_surge_ratio(
    volume_chrono: pd.Series,
    *,
    lookback: int = 50,
) -> float | None:
    """Latest volume divided by the preceding lookback-session average."""

    if volume_chrono is None or len(volume_chrono) < 2:
        return None
    volume = pd.to_numeric(volume_chrono, errors="coerce").dropna()
    if len(volume) < 2:
        return None

    latest = float(volume.iloc[-1])
    prior = volume.iloc[max(0, len(volume) - lookback - 1) : -1]
    if prior.empty:
        return None
    baseline = float(prior.mean())
    if baseline <= 0:
        return None
    return round(latest / baseline, 4)


def _distance_from_52w_high(
    data: StockData,
    close_chrono: pd.Series,
) -> float | None:
    """Calculate distance from the trailing 252-session closing high.

    V2 deliberately recomputes the high from the chronological price series.
    The shared precomputed context can be built from a longer fetch window, so
    using its generic ``high_52w`` field here could accidentally make N a
    two-year-high test instead of a trailing-52-week test.
    """

    if close_chrono is None or close_chrono.empty:
        return None

    precomputed = data.precomputed_scan_context
    current_price = (
        _number(precomputed.current_price)
        if precomputed is not None
        else None
    )
    if current_price is None:
        current_price = _number(close_chrono.iloc[-1])

    high_52w = _number(
        pd.to_numeric(close_chrono, errors="coerce").dropna().tail(252).max()
    )

    if current_price is None or high_52w is None or high_52w <= 0:
        return None
    return round(max(0.0, ((high_52w - current_price) / high_52w) * 100.0), 4)


def extract_v2_inputs(
    data: StockData,
    *,
    rs_rating: float | None,
    market_exposure_score: float | None,
    group_rank: int | None = None,
    catalyst_recent: bool | None = None,
) -> CANSLIMV2Inputs:
    """Extract V2 scalar inputs from the existing scan data contract."""

    fundamentals = data.fundamentals or {}
    quarterly = data.quarterly_growth or {}
    close_chrono, volume_chrono = _chronological_series(data)

    # C must use comparable-quarter YoY, never sequential QoQ.
    eps_yoy = _number(fundamentals.get("eps_q1_yoy"))
    if eps_yoy is None:
        eps_yoy = _number(quarterly.get("eps_growth_yy"))
    prior_eps_yoy = _number(fundamentals.get("eps_q2_yoy"))
    sales_yoy = _number(quarterly.get("sales_growth_yy"))
    if sales_yoy is None:
        sales_yoy = _number(fundamentals.get("sales_growth_yy"))

    volume_surge = calculate_volume_surge_ratio(volume_chrono)

    return CANSLIMV2Inputs(
        eps_yoy=eps_yoy,
        prior_eps_yoy=prior_eps_yoy,
        sales_yoy=sales_yoy,
        eps_cagr=_number(fundamentals.get("eps_5yr_cagr")),
        eps_years_available=int(fundamentals.get("eps_years_available") or 0),
        eps_rating=_number(fundamentals.get("eps_rating")),
        roe=_number(fundamentals.get("roe")),
        distance_from_52w_high_pct=_distance_from_52w_high(data, close_chrono),
        catalyst_recent=catalyst_recent,
        breakout_volume_ratio=volume_surge,
        up_down_volume_ratio=calculate_up_down_volume_ratio(
            close_chrono, volume_chrono
        ),
        volume_surge_ratio=volume_surge,
        shares_outstanding_millions=_shares_millions(
            fundamentals.get("shares_outstanding")
        ),
        rs_rating=_number(rs_rating),
        group_rank=group_rank,
        institutional_ownership_pct=_ownership_pct(
            fundamentals.get("institutional_ownership")
        ),
        ownership_change_pct=_number(fundamentals.get("institutional_change")),
        institutional_transactions_pct=_number(
            fundamentals.get("institutional_transactions")
        ),
        market_exposure_score=_number(market_exposure_score),
    )


def evaluate_v2_inputs(inputs: CANSLIMV2Inputs) -> CANSLIMV2Scorecard:
    """Evaluate extracted inputs with the pure criterion functions."""

    results: list[CriterionResult] = [
        score_current_earnings(
            eps_yoy=inputs.eps_yoy,
            prior_eps_yoy=inputs.prior_eps_yoy,
            sales_yoy=inputs.sales_yoy,
        ),
        score_annual_earnings(
            eps_cagr=inputs.eps_cagr,
            years_available=inputs.eps_years_available,
            eps_rating=inputs.eps_rating,
            roe=inputs.roe,
        ),
        score_new_highs(
            distance_from_52w_high_pct=inputs.distance_from_52w_high_pct,
            catalyst_recent=inputs.catalyst_recent,
            breakout_volume_ratio=inputs.breakout_volume_ratio,
        ),
        score_supply_demand(
            up_down_volume_ratio=inputs.up_down_volume_ratio,
            volume_surge_ratio=inputs.volume_surge_ratio,
            shares_outstanding_millions=inputs.shares_outstanding_millions,
        ),
        score_leader(
            rs_rating=inputs.rs_rating,
            group_rank=inputs.group_rank,
        ),
        score_institutional_sponsorship(
            institutional_ownership_pct=inputs.institutional_ownership_pct,
            ownership_change_pct=inputs.ownership_change_pct,
            institutional_transactions_pct=inputs.institutional_transactions_pct,
        ),
        score_market_gate(exposure_score=inputs.market_exposure_score),
    ]
    return build_scorecard(results)


def evaluate_stock_data(
    data: StockData,
    *,
    rs_rating: float | None,
    market_exposure_score: float | None,
    group_rank: int | None = None,
    catalyst_recent: bool | None = None,
) -> CANSLIMV2Scorecard:
    """Convenience adapter for an unregistered future V2 scanner."""

    return evaluate_v2_inputs(
        extract_v2_inputs(
            data,
            rs_rating=rs_rating,
            market_exposure_score=market_exposure_score,
            group_rank=group_rank,
            catalyst_recent=catalyst_recent,
        )
    )
