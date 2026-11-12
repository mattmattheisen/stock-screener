"""Compatibility checks: preserve raw OHLCV when adjusted values are missing."""
from datetime import date

import pandas as pd

from app.services.price_row_normalization import (
    normalize_price_frame,
    stock_price_row_from_ohlcv,
)
from app.services.price_value_policy import protect_existing_adjusted_close


def test_cached_frame_retains_valid_raw_price_with_missing_adjustment():
    frame = pd.DataFrame({
        "Open": [100.0],
        "High": [101.0],
        "Low": [99.0],
        "Close": [100.5],
        "Adj Close": [None],
        "Volume": [12345],
    }, index=pd.to_datetime([date(2026, 11, 11)]))
    result = normalize_price_frame(frame)
    assert result is not None and len(result) == 1
    assert result.iloc[0]["Close"] == 100.5
    assert pd.isna(result.iloc[0]["Adj Close"])


def test_new_missing_adj_uses_nullable_stock_price_column():
    frame = pd.Series({
        "Open": 100., "High": 101., "Low": 99.,
        "Close": 100.5, "Volume": 12345,
    })
    mapping = stock_price_row_from_ohlcv(
        symbol="MSFT", row_date=date(2026, 11, 11), row=frame
    )
    assert mapping is not None
    assert mapping["close"] == 100.5
    assert mapping["adj_close"] is None


def test_missing_refresh_does_not_erase_existing_adj():
    mapping = {"adj_close": None, "close": 101.0}
    updated = protect_existing_adjusted_close(mapping, 99.5)
    assert updated["adj_close"] == 99.5
    assert mapping["adj_close"] is None
