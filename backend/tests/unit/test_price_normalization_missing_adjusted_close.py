"""Regression: an absent adjusted close must never masquerade as raw close.

Research-branch change to the shared stock-price ingestion contract.
"""
from datetime import date

from app.services.price_row_normalization import stock_price_row_from_ohlcv


def _row(**overrides):
    values = {
        "Open": 100.0, "High": 102.0, "Low": 99.0,
        "Close": 101.0, "Volume": 12345,
    }
    values.update(overrides)
    return values


def test_missing_adjusted_close_remains_null():
    result = stock_price_row_from_ohlcv(
        symbol="MSFT", row_date=date(2026, 11, 11), row=_row()
    )
    assert result is not None
    assert result["close"] == 101.0
    assert result["adj_close"] is None


def test_explicit_adjusted_close_is_preserved():
    result = stock_price_row_from_ohlcv(
        symbol="MSFT", row_date=date(2026, 11, 11),
        row=_row(**{"Adj Close": 98.75}),
    )
    assert result is not None
    assert result["adj_close"] == 98.75


def test_explicit_equal_adjusted_close_is_not_reinterpreted():
    result = stock_price_row_from_ohlcv(
        symbol="MSFT", row_date=date(2026, 11, 11),
        row=_row(**{"Adj Close": 101.0}),
    )
    assert result is not None
    # Equality alone is not evidence that an adjustment was performed.
    assert result["adj_close"] == 101.0
