"""Tests for mapping the existing scan data contract into CAN SLIM V2."""

from types import SimpleNamespace

import pandas as pd

from app.scanners.base_screener import StockData
from app.scanners.criteria.canslim_v2_adapter import (
    calculate_up_down_volume_ratio,
    extract_v2_inputs,
    evaluate_stock_data,
)


def _price_frame(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": volumes,
        }
    )


def _stock_data(
    *,
    closes: list[float],
    volumes: list[float],
    fundamentals: dict | None = None,
    quarterly_growth: dict | None = None,
) -> StockData:
    frame = _price_frame(closes, volumes)
    return StockData(
        symbol="TEST",
        price_data=frame,
        benchmark_data=frame.copy(),
        fundamentals=fundamentals,
        quarterly_growth=quarterly_growth,
    )


def test_adapter_prefers_comparable_quarter_eps_yoy_over_sequential_qoq() -> None:
    data = _stock_data(
        closes=[90.0, 95.0, 100.0],
        volumes=[100.0, 100.0, 200.0],
        fundamentals={
            "eps_q1_yoy": 32.0,
            "eps_q2_yoy": 20.0,
            "eps_5yr_cagr": 28.0,
            "eps_years_available": 5,
        },
        quarterly_growth={
            "eps_growth_qq": -8.0,
            "eps_growth_yy": 31.0,
            "sales_growth_yy": 26.0,
        },
    )

    inputs = extract_v2_inputs(
        data,
        rs_rating=85.0,
        market_exposure_score=70.0,
    )

    assert inputs.eps_yoy == 32.0
    assert inputs.prior_eps_yoy == 20.0
    assert inputs.sales_yoy == 26.0


def test_adapter_falls_back_to_cadence_comparable_yoy_when_eps_rating_component_missing() -> None:
    data = _stock_data(
        closes=[90.0, 95.0, 100.0],
        volumes=[100.0, 100.0, 200.0],
        fundamentals={},
        quarterly_growth={
            "eps_growth_qq": 5.0,
            "eps_growth_yy": 29.0,
        },
    )

    inputs = extract_v2_inputs(
        data,
        rs_rating=85.0,
        market_exposure_score=70.0,
    )

    assert inputs.eps_yoy == 29.0


def test_up_down_volume_ratio_uses_chronological_price_direction() -> None:
    close = pd.Series([10.0, 11.0, 10.0, 12.0])
    volume = pd.Series([100.0, 300.0, 100.0, 400.0])

    ratio = calculate_up_down_volume_ratio(close, volume)

    # Up days carry 300 + 400 volume; the one down day carries 100.
    assert ratio == 7.0


def test_adapter_normalizes_shares_and_fractional_institutional_ownership() -> None:
    data = _stock_data(
        closes=[90.0, 95.0, 100.0],
        volumes=[100.0, 100.0, 200.0],
        fundamentals={
            "shares_outstanding": 50_000_000,
            "institutional_ownership": 0.88,
            "institutional_change": 2.0,
        },
    )

    inputs = extract_v2_inputs(
        data,
        rs_rating=85.0,
        market_exposure_score=70.0,
    )

    assert inputs.shares_outstanding_millions == 50.0
    assert inputs.institutional_ownership_pct == 88.0


def test_adapter_uses_trailing_252_sessions_for_52_week_high() -> None:
    # An old 2-year high of 200 should not contaminate the trailing 52-week high.
    closes = [200.0] + [100.0] * 47 + [110.0] * 252
    volumes = [100.0] * len(closes)
    data = _stock_data(closes=closes, volumes=volumes)

    inputs = extract_v2_inputs(
        data,
        rs_rating=85.0,
        market_exposure_score=70.0,
    )

    assert inputs.distance_from_52w_high_pct == 0.0


def test_adapter_ignores_contaminated_precomputed_two_year_high() -> None:
    closes = [200.0] + [100.0] * 47 + [110.0] * 252
    volumes = [100.0] * len(closes)
    data = _stock_data(closes=closes, volumes=volumes)
    close = data.price_data["Close"].reset_index(drop=True)
    volume = data.price_data["Volume"].reset_index(drop=True)
    data.precomputed_scan_context = SimpleNamespace(
        close_chrono=close,
        volume_chrono=volume,
        current_price=110.0,
        high_52w=200.0,
    )

    inputs = extract_v2_inputs(
        data,
        rs_rating=85.0,
        market_exposure_score=70.0,
    )

    assert inputs.distance_from_52w_high_pct == 0.0


def test_unregistered_adapter_can_build_actionable_scorecard_from_existing_fields() -> None:
    closes = [80.0 + i * 0.2 for i in range(260)]
    volumes = [100.0 + (i % 3) * 20.0 for i in range(259)] + [250.0]
    data = _stock_data(
        closes=closes,
        volumes=volumes,
        fundamentals={
            "eps_q1_yoy": 45.0,
            "eps_q2_yoy": 30.0,
            "eps_5yr_cagr": 32.0,
            "eps_years_available": 5,
            "eps_rating": 90.0,
            "roe": 22.0,
            "shares_outstanding": 60_000_000,
            "institutional_ownership": 0.65,
            "institutional_change": 3.0,
            "institutional_transactions": 2.0,
        },
        quarterly_growth={"sales_growth_yy": 30.0},
    )

    scorecard = evaluate_stock_data(
        data,
        rs_rating=92.0,
        market_exposure_score=72.0,
        group_rank=20,
        catalyst_recent=True,
    )

    assert scorecard.stock_score >= 70.0
    assert scorecard.stock_passes is True
    assert scorecard.market_passes is True
    assert scorecard.actionable is True
