from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.market_breadth import MarketBreadth
from app.models.stock_universe import UNIVERSE_STATUS_ACTIVE, StockUniverse
from app.services.breadth_backfill import BreadthBackfillPlan
from app.services.breadth_calculator_service import BreadthCalculatorService
from app.services.static_breadth_eligibility import (
    static_breadth_eligibility_signature,
)


def _flat_price_df(
    end_date: date,
    close: float = 100.0,
    periods: int = 80,
) -> pd.DataFrame:
    index = pd.bdate_range(end=end_date, periods=periods)
    closes = [close] * len(index)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(index),
        },
        index=index,
    )


def _make_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[StockUniverse.__table__, MarketBreadth.__table__],
    )
    return sessionmaker(bind=engine)()


def test_backfill_plan_canonicalizes_symbols_and_derives_signature():
    calculation_date = date(2026, 3, 20)
    expected_signature = static_breadth_eligibility_signature(("AAA", "BBB"))

    plan = BreadthBackfillPlan.from_legacy(
        dates=[calculation_date],
        eligible_symbols_by_date={
            calculation_date: ("BBB", "AAA", "AAA"),
        },
        eligibility_signatures_by_date={
            calculation_date: expected_signature,
        },
    )

    universe = plan.universe_for(calculation_date)
    assert universe is not None
    assert universe.symbols == ("AAA", "BBB")
    assert universe.eligibility_signature == expected_signature


@pytest.mark.parametrize(
    ("eligible_symbols_by_date", "eligibility_signatures_by_date"),
    [
        ({date(2026, 3, 20): ("AAA",)}, None),
        (None, {date(2026, 3, 20): "signature"}),
    ],
)
def test_backfill_plan_rejects_half_supplied_legacy_contract(
    eligible_symbols_by_date,
    eligibility_signatures_by_date,
):
    with pytest.raises(ValueError, match="must be supplied together"):
        BreadthBackfillPlan.from_legacy(
            dates=[date(2026, 3, 20)],
            eligible_symbols_by_date=eligible_symbols_by_date,
            eligibility_signatures_by_date=eligibility_signatures_by_date,
        )


def test_backfill_plan_rejects_missing_requested_date():
    with pytest.raises(ValueError, match="missing for 2026-03-21"):
        BreadthBackfillPlan.from_legacy(
            dates=[date(2026, 3, 20), date(2026, 3, 21)],
            eligible_symbols_by_date={
                date(2026, 3, 20): ("AAA",),
            },
            eligibility_signatures_by_date={
                date(2026, 3, 20): static_breadth_eligibility_signature(("AAA",)),
            },
        )


def test_backfill_plan_rejects_signature_for_different_symbols():
    calculation_date = date(2026, 3, 20)

    with pytest.raises(ValueError, match="signature does not match"):
        BreadthBackfillPlan.from_legacy(
            dates=[calculation_date],
            eligible_symbols_by_date={calculation_date: ("AAA",)},
            eligibility_signatures_by_date={
                calculation_date: static_breadth_eligibility_signature(("BBB",)),
            },
        )


def test_backfill_plan_without_explicit_eligibility_preserves_legacy_mode():
    calculation_date = date(2026, 3, 20)

    plan = BreadthBackfillPlan.from_legacy(
        dates=[calculation_date],
        eligible_symbols_by_date=None,
        eligibility_signatures_by_date=None,
    )

    assert plan.dates == (calculation_date,)
    assert plan.universe_for(calculation_date) is None

def test_backfill_range_reuses_loaded_histories_and_computes_chronological_ratios(monkeypatch):
    db = _make_db_session()
    db.add_all([
        StockUniverse(symbol="AAA", is_active=True, status=UNIVERSE_STATUS_ACTIVE),
        StockUniverse(symbol="BBB", is_active=True, status=UNIVERSE_STATUS_ACTIVE),
    ])

    prior_dates = [date(2026, 3, day) for day in range(2, 12)]
    for prior_date in prior_dates:
        db.add(MarketBreadth(
            date=prior_date,
            stocks_up_4pct=2,
            stocks_down_4pct=1,
            ratio_5day=2.0,
            ratio_10day=2.0,
            stocks_up_25pct_quarter=0,
            stocks_down_25pct_quarter=0,
            stocks_up_25pct_month=0,
            stocks_down_25pct_month=0,
            stocks_up_50pct_month=0,
            stocks_down_50pct_month=0,
            stocks_up_13pct_34days=0,
            stocks_down_13pct_34days=0,
            total_stocks_scanned=2,
            broad_universe_count=2,
            calculation_revision=2,
        ))
    db.commit()

    aaa_df = _flat_price_df(date(2026, 3, 13))
    bbb_df = _flat_price_df(date(2026, 3, 13))
    aaa_df.loc[pd.Timestamp(date(2026, 3, 12)), ["Close", "Adj Close"]] = 105.0
    aaa_df.loc[pd.Timestamp(date(2026, 3, 13)), ["Close", "Adj Close"]] = 110.0
    bbb_df.loc[pd.Timestamp(date(2026, 3, 12)), ["Close", "Adj Close"]] = 95.0
    bbb_df.loc[pd.Timestamp(date(2026, 3, 13)), ["Close", "Adj Close"]] = 100.0
    for frame in (aaa_df, bbb_df):
        frame.loc[pd.Timestamp(date(2026, 3, 12)), "Volume"] = 1_100_000
        frame.loc[pd.Timestamp(date(2026, 3, 13)), "Volume"] = 1_200_000

    price_cache = MagicMock()
    price_cache.get_many_cached_only_fresh.return_value = {"AAA": aaa_df, "BBB": None}
    price_cache.get_historical_data.return_value = bbb_df
    service = BreadthCalculatorService(db, price_cache)
    trading_dates = [date(2026, 3, 12), date(2026, 3, 13)]

    result = service.backfill_range(trading_dates[0], trading_dates[-1], trading_dates=trading_dates)

    assert result == {
        "total_dates": 2,
        "processed": 2,
        "errors": 0,
        "error_dates": [],
    }
    price_cache.get_many_cached_only_fresh.assert_called_once_with(["AAA", "BBB"], period="2y")
    price_cache.get_many_cached_only.assert_not_called()
    price_cache.get_historical_data.assert_called_once_with(symbol="BBB", period="2y")

    stored = db.query(MarketBreadth).filter(
        MarketBreadth.date.in_(trading_dates)
    ).order_by(MarketBreadth.date.asc()).all()

    assert len(stored) == 2
    assert stored[0].stocks_up_4pct == 1
    assert stored[0].stocks_down_4pct == 1
    assert stored[0].ratio_5day == 1.8
    assert stored[0].ratio_10day == 1.9
    assert stored[1].stocks_up_4pct == 2
    assert stored[1].stocks_down_4pct == 0
    assert stored[1].ratio_5day == 2.25
    assert stored[1].ratio_10day == 2.11

def test_backfill_range_scans_only_explicit_date_specific_eligible_symbols():
    db = _make_db_session()
    first_date = date(2026, 3, 19)
    second_date = date(2026, 3, 20)
    price_cache = MagicMock()
    price_cache.get_many_cached_only_fresh.return_value = {
        "AAA": _flat_price_df(second_date),
        "BBB": _flat_price_df(second_date),
    }
    service = BreadthCalculatorService(db, price_cache)
    aaa_signature = static_breadth_eligibility_signature(("AAA",))
    bbb_signature = static_breadth_eligibility_signature(("BBB",))

    result = service.backfill_range(
        first_date,
        second_date,
        trading_dates=[first_date, second_date],
        eligible_symbols_by_date={
            first_date: ("AAA",),
            second_date: ("BBB",),
        },
        eligibility_signatures_by_date={
            first_date: aaa_signature,
            second_date: bbb_signature,
        },
    )

    price_cache.get_many_cached_only_fresh.assert_called_once_with(
        ["AAA", "BBB"], period="2y"
    )
    assert result["eligible_stocks_by_date"] == {
        "2026-03-19": 1,
        "2026-03-20": 1,
    }
    assert result["scanned_stocks_by_date"] == {
        "2026-03-19": 1,
        "2026-03-20": 1,
    }
    assert result["broad_universe_stocks_by_date"] == {
        "2026-03-19": 1,
        "2026-03-20": 1,
    }
    assert result["calculation_errors_by_date"] == {
        "2026-03-19": 0,
        "2026-03-20": 0,
    }
    stored = {
        row.date: row.eligibility_signature
        for row in db.query(MarketBreadth).filter(
            MarketBreadth.date.in_([first_date, second_date])
        )
    }
    assert stored == {first_date: aaa_signature, second_date: bbb_signature}


def test_backfill_range_validates_historical_symbols_on_their_eligible_date():
    db = _make_db_session()
    historical_date = date(2026, 3, 19)
    current_date = date(2026, 3, 20)
    eligible_date_by_symbol = {
        "CURRENT": current_date,
        "HISTORICAL": historical_date,
    }

    def cached_prices(symbols, period, *, required_as_of_date):
        assert period == "2y"
        return {
            symbol: (
                _flat_price_df(eligible_date_by_symbol[symbol])
                if required_as_of_date == eligible_date_by_symbol[symbol]
                else None
            )
            for symbol in symbols
        }

    price_cache = MagicMock()
    price_cache.get_many_cached_only_fresh.side_effect = cached_prices
    service = BreadthCalculatorService(db, price_cache)

    result = service.backfill_range(
        historical_date,
        current_date,
        trading_dates=[historical_date, current_date],
        cache_only=True,
        required_as_of_date=current_date,
        eligible_symbols_by_date={
            historical_date: ("HISTORICAL",),
            current_date: ("CURRENT",),
        },
        eligibility_signatures_by_date={
            historical_date: static_breadth_eligibility_signature(("HISTORICAL",)),
            current_date: static_breadth_eligibility_signature(("CURRENT",)),
        },
    )

    assert result["scanned_stocks_by_date"] == {
        "2026-03-19": 1,
        "2026-03-20": 1,
    }
    assert result["broad_universe_stocks_by_date"] == {
        "2026-03-19": 1,
        "2026-03-20": 1,
    }


def test_backfill_range_rejects_signature_for_different_eligible_symbols():
    db = _make_db_session()
    calculation_date = date(2026, 3, 20)
    service = BreadthCalculatorService(db, MagicMock())

    with pytest.raises(ValueError, match="signature does not match"):
        service.backfill_range(
            calculation_date,
            calculation_date,
            trading_dates=[calculation_date],
            eligible_symbols_by_date={calculation_date: ("AAA",)},
            eligibility_signatures_by_date={calculation_date: "wrong"},
        )
