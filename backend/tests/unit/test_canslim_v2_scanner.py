"""Direct tests for the intentionally unregistered CAN SLIM V2 scanner."""

from types import SimpleNamespace

import pandas as pd

from app.scanners.base_screener import StockData
from app.scanners.canslim_v2_scanner import CANSLIMV2Scanner


def _frame(n: int = 260) -> pd.DataFrame:
    closes = [80.0 + i * 0.2 for i in range(n)]
    volumes = [100.0 + (i % 3) * 20.0 for i in range(n - 1)] + [250.0]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": volumes,
        }
    )


def _data() -> StockData:
    frame = _frame()
    close = frame["Close"].reset_index(drop=True)
    volume = frame["Volume"].reset_index(drop=True)
    precomputed = SimpleNamespace(
        close_chrono=close,
        close_rev=close[::-1].reset_index(drop=True),
        volume_chrono=volume,
        volume_rev=volume[::-1].reset_index(drop=True),
        benchmark_close_chrono=close,
        benchmark_close_rev=close[::-1].reset_index(drop=True),
        current_price=float(close.iloc[-1]),
        high_52w=float(close.tail(252).max()),
        rs_ratings={
            "rs_rating": 92.0,
            "rs_rating_1m": 90.0,
            "rs_rating_3m": 91.0,
            "rs_rating_12m": 93.0,
        },
    )
    return StockData(
        symbol="TEST",
        price_data=frame,
        benchmark_data=frame.copy(),
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
        precomputed_scan_context=precomputed,
    )


def test_v2_scanner_is_directly_exercisable_without_registration() -> None:
    scanner = CANSLIMV2Scanner()

    result = scanner.scan_stock(
        "TEST",
        _data(),
        criteria={
            "market_exposure_score": 72.0,
            "group_rank": 20,
            "catalyst_recent": True,
        },
    )

    assert scanner.screener_name == "canslim_v2"
    assert result.score >= 70.0
    assert result.passes is True
    assert result.rating in {"Buy", "Strong Buy"}
    assert result.details["methodology_version"] == "canslim_v2"
    assert result.details["market"]["points"] == 0.0


def test_market_gate_blocks_pass_without_rewriting_stock_score() -> None:
    scanner = CANSLIMV2Scanner()
    data = _data()

    uptrend = scanner.scan_stock(
        "TEST",
        data,
        criteria={"market_exposure_score": 72.0, "group_rank": 20},
    )
    correction = scanner.scan_stock(
        "TEST",
        data,
        criteria={"market_exposure_score": 20.0, "group_rank": 20},
    )

    assert correction.score == uptrend.score
    assert uptrend.passes is True
    assert correction.passes is False
    assert correction.rating == "Market Blocked"


def test_missing_market_context_is_visible_not_silently_assumed() -> None:
    scanner = CANSLIMV2Scanner()

    result = scanner.scan_stock("TEST", _data(), criteria={})

    assert result.score >= 70.0
    assert result.passes is False
    assert result.rating == "Market Unknown"
    assert result.details["status"] == "market_unknown"
