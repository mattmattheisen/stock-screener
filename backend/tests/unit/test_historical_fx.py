from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.services.historical_fx import (
    MissingHistoricalFXError,
    resolve_historical_fx_series,
)


def test_historical_fx_prefers_exact_date_then_prior_within_seven_days() -> None:
    requested = (date(2026, 8, 20), date(2026, 8, 21))

    result = resolve_historical_fx_series(
        "HKD",
        requested,
        {
            date(2026, 8, 14): 0.127,
            date(2026, 8, 21): 0.128,
        },
        max_age_days=7,
    )

    assert result.loc[pd.Timestamp("2026-08-20")] == pytest.approx(0.127)
    assert result.loc[pd.Timestamp("2026-08-21")] == pytest.approx(0.128)


def test_historical_fx_rejects_quote_older_than_seven_calendar_days() -> None:
    with pytest.raises(MissingHistoricalFXError) as exc_info:
        resolve_historical_fx_series(
            "HKD",
            (date(2026, 8, 22),),
            {date(2026, 8, 14): 0.127},
            max_age_days=7,
        )

    assert exc_info.value.currency == "HKD"
    assert exc_info.value.calculation_date == date(2026, 8, 22)


def test_historical_fx_never_uses_future_quote() -> None:
    with pytest.raises(MissingHistoricalFXError):
        resolve_historical_fx_series(
            "HKD",
            (date(2026, 8, 21),),
            {date(2026, 8, 22): 0.128},
            max_age_days=7,
        )


def test_historical_fx_usd_is_identity_without_observations() -> None:
    result = resolve_historical_fx_series(
        "usd",
        (date(2026, 8, 20), date(2026, 8, 21)),
        {},
        max_age_days=7,
    )

    assert result.tolist() == [1.0, 1.0]
