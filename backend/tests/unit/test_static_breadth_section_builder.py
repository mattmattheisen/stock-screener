from datetime import date

import pandas as pd
import pytest
from app.services.point_in_time_universe_service import PointInTimeUniverse
from app.services.static_breadth_section_builder import (
    StaticBreadthEngineInputFactory,
    StaticBreadthSectionBuilder,
)
from app.services.static_site_errors import StaticSiteSectionUnavailableError


def _price_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0,
            "Adj Close": 100.0,
            "Volume": 1_000_000,
        },
        index=index,
    )


class _HistoricalFx:
    def get_historical_usd_rates(self, currencies, required_dates):
        return {
            currency: pd.Series(
                0.13,
                index=pd.DatetimeIndex(sorted(required_dates)),
            )
            for currency in currencies
        }


def test_static_inputs_retain_only_the_feature_window_for_prices_and_fx():
    recent_index = pd.bdate_range(end="2026-08-21", periods=400)
    full_index = pd.DatetimeIndex([pd.Timestamp("2020-01-02"), *recent_index])
    canonical_dates = list(recent_index[-120:].date)

    inputs = StaticBreadthEngineInputFactory(
        fx_service=_HistoricalFx()
    ).build(
        market="HK",
        canonical_dates=canonical_dates,
        price_data={"0700.HK": _price_frame(full_index)},
        currencies_by_symbol={"0700.HK": "HKD"},
    )

    retained_index = inputs.request.prices_by_symbol["0700.HK"].index
    assert len(retained_index) == 371
    assert retained_index[0] == recent_index[29]
    assert pd.Timestamp("2020-01-02") not in retained_index
    assert pd.Timestamp("2020-01-02") not in inputs.request.fx_by_currency["HKD"].index


class _EmptyUniverseResolver:
    def resolve(self, _db, *, market, as_of_date):
        return PointInTimeUniverse(
            market=market,
            as_of_date=as_of_date,
            symbols=(),
            universe_hash="empty",
        )


def test_static_builder_does_not_fall_back_when_database_universe_is_empty():
    builder = StaticBreadthSectionBuilder(
        ui_snapshot_service=object(),
        price_cache=object(),
        benchmark_cache=object(),
        universe_resolver=_EmptyUniverseResolver(),
    )

    with pytest.raises(
        StaticSiteSectionUnavailableError,
        match="No common-stock universe is available",
    ):
        builder.build(
            generated_at="2026-08-21T22:00:00Z",
            expected_as_of_date=date(2026, 8, 21),
            market="US",
            serialized_rows=[{"symbol": "ETF"}],
            db=object(),
        )
