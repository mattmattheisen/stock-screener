from __future__ import annotations

from datetime import date

from app.models.stock import StockPrice


class _Calendar:
    def __init__(self) -> None:
        self.trading_day_calls: list[tuple[str, date, date]] = []

    def trading_days(self, market, start, end):
        assert market == "IN"
        self.trading_day_calls.append((market, start, end))
        return [
            session
            for session in (
                date(2026, 2, 2),
                date(2026, 3, 2),
                date(2026, 5, 18),
                date(2026, 6, 4),
            )
            if start <= session <= end
        ]

    @staticmethod
    def session_anchors(market, as_of_date, *, offsets):
        assert market == "IN"
        assert as_of_date == date(2026, 5, 18)
        assert tuple(offsets) == (69,)
        return {
            0: as_of_date,
            69: date(2026, 2, 2),
        }


def _price(symbol: str, day: date, close: float | None) -> StockPrice:
    return StockPrice(
        symbol=symbol,
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=1000,
    )


def test_breadth_history_required_dates_use_exact_69_session_warmup_anchor() -> None:
    from app.services.breadth_history_price_coverage import (
        BreadthHistoryPriceCoverageService,
    )

    calendar = _Calendar()
    service = BreadthHistoryPriceCoverageService(
        calendar_service=calendar,
        lookback_days=20,
    )

    required_dates = service.required_price_dates(
        market="IN",
        through_date=date(2026, 6, 4),
    )

    assert required_dates == frozenset(
        {
            date(2026, 2, 2),
            date(2026, 3, 2),
            date(2026, 5, 18),
            date(2026, 6, 4),
        }
    )
    assert calendar.trading_day_calls == [
        ("IN", date(2026, 5, 15), date(2026, 6, 4)),
        ("IN", date(2026, 2, 2), date(2026, 6, 4)),
    ]


def test_breadth_history_price_coverage_requires_every_usable_required_ohlc(
    universe_session,
) -> None:
    from app.services.breadth_history_price_coverage import (
        BreadthHistoryPriceCoverageService,
    )

    service = BreadthHistoryPriceCoverageService(
        calendar_service=_Calendar(),
        lookback_days=20,
    )
    required_dates = service.required_price_dates(
        market="IN",
        through_date=date(2026, 6, 4),
    )

    universe_session.add_all(
        [
            *[_price("FULL.NS", day, 100.0) for day in required_dates],
            *[
                _price("SHORT.NS", day, 50.0)
                for day in required_dates
                if day != date(2026, 2, 2)
            ],
            *[
                _price("BAD.NS", day, None if day == date(2026, 3, 2) else 25.0)
                for day in required_dates
            ],
            *[
                StockPrice(
                    symbol="PARTIAL.NS",
                    date=day,
                    open=None if day == date(2026, 3, 2) else 75.0,
                    high=75.0,
                    low=75.0,
                    close=75.0,
                    adj_close=75.0,
                    volume=1000,
                )
                for day in required_dates
            ],
        ]
    )
    universe_session.commit()

    coverage = service.classify(
        universe_session,
        market="IN",
        through_date=date(2026, 6, 4),
        symbols=("FULL.NS", "SHORT.NS", "BAD.NS", "PARTIAL.NS", "NONE.NS"),
    )

    assert coverage.required_price_date_count == len(required_dates)
    assert coverage.complete_symbols == ("FULL.NS",)
    assert coverage.incomplete_symbols == (
        "SHORT.NS",
        "BAD.NS",
        "PARTIAL.NS",
        "NONE.NS",
    )
    assert coverage.available_price_date_counts["SHORT.NS"] == len(required_dates) - 1
    assert coverage.available_price_date_counts["BAD.NS"] == len(required_dates) - 1
    assert coverage.available_price_date_counts["PARTIAL.NS"] == len(required_dates) - 1
    assert coverage.incomplete_samples == (
        "SHORT.NS",
        "BAD.NS",
        "PARTIAL.NS",
        "NONE.NS",
    )
