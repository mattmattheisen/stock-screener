from __future__ import annotations

from datetime import date

from sqlalchemy import event

from app.models.stock import StockFundamental, StockPrice


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


class _WarmupCalendar:
    def trading_days(self, market, start, end):
        assert market == "IN"
        return [
            session
            for session in (
                date(2026, 1, 2),
                date(2026, 1, 5),
                date(2026, 1, 6),
                date(2026, 1, 7),
                date(2026, 1, 8),
            )
            if start <= session <= end
        ]

    @staticmethod
    def session_anchors(market, as_of_date, *, offsets):
        assert market == "IN"
        assert as_of_date == date(2026, 1, 6)
        assert tuple(offsets) == (2,)
        return {
            0: as_of_date,
            2: date(2026, 1, 2),
        }


class _ObservedWarmupCalendar:
    def trading_days(self, market, start, end):
        assert market == "IN"
        return [
            session
            for session in (
                date(2025, 12, 31),
                date(2026, 1, 2),
                date(2026, 1, 5),
                date(2026, 1, 6),
                date(2026, 1, 7),
                date(2026, 1, 8),
            )
            if start <= session <= end
        ]

    @staticmethod
    def session_anchors(market, as_of_date, *, offsets):
        assert market == "IN"
        assert as_of_date == date(2026, 1, 6)
        assert tuple(offsets) == (2,)
        return {
            0: as_of_date,
            2: date(2026, 1, 2),
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
    assert coverage.history_incomplete_symbols == (
        "SHORT.NS",
        "BAD.NS",
        "PARTIAL.NS",
        "NONE.NS",
    )
    assert coverage.missing_through_date_symbols == ()
    assert coverage.available_price_date_counts["SHORT.NS"] == len(required_dates) - 1
    assert coverage.available_price_date_counts["BAD.NS"] == len(required_dates) - 1
    assert coverage.available_price_date_counts["PARTIAL.NS"] == len(required_dates) - 1
    assert coverage.incomplete_samples == (
        "SHORT.NS",
        "BAD.NS",
        "PARTIAL.NS",
        "NONE.NS",
    )


def test_breadth_history_price_coverage_uses_observed_bars_not_every_session(
    universe_session,
) -> None:
    from app.services.breadth_history_price_coverage import (
        BreadthHistoryPriceCoverageService,
    )

    service = BreadthHistoryPriceCoverageService(warmup_sessions=2)
    required_dates = (
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    as_of_date = date(2026, 1, 8)

    universe_session.add_all(
        [
            StockFundamental(symbol="LATE.NS", ipo_date=required_dates[-3]),
            *[_price("LATE.NS", day, 100.0) for day in required_dates[-3:]],
            *[_price("NOASOF.NS", day, 50.0) for day in required_dates[:3]],
            *[_price("SHORT.NS", day, 25.0) for day in required_dates[-2:]],
        ]
    )
    universe_session.commit()

    coverage = service.classify(
        universe_session,
        market="IN",
        through_date=as_of_date,
        symbols=("LATE.NS", "NOASOF.NS", "SHORT.NS"),
        required_price_dates=required_dates,
    )

    assert coverage.complete_symbols == ("LATE.NS",)
    assert coverage.incomplete_symbols == ("NOASOF.NS", "SHORT.NS")
    assert coverage.history_incomplete_symbols == ("SHORT.NS",)
    assert coverage.missing_through_date_symbols == ("NOASOF.NS",)
    assert coverage.available_price_date_counts == {
        "LATE.NS": 3,
        "NOASOF.NS": 3,
        "SHORT.NS": 2,
    }


def test_breadth_history_price_coverage_requires_warmup_by_oldest_target_session(
    universe_session,
) -> None:
    from app.services.breadth_history_price_coverage import (
        BreadthHistoryPriceCoverageService,
    )

    service = BreadthHistoryPriceCoverageService(
        calendar_service=_WarmupCalendar(),
        lookback_days=2,
        warmup_sessions=2,
    )
    as_of_date = date(2026, 1, 8)

    universe_session.add_all(
        [
            *[
                _price("READY.NS", day, 100.0)
                for day in (
                    date(2026, 1, 2),
                    date(2026, 1, 5),
                    date(2026, 1, 6),
                    date(2026, 1, 8),
                )
            ],
            *[
                _price("RECENT.NS", day, 50.0)
                for day in (
                    date(2026, 1, 6),
                    date(2026, 1, 7),
                    date(2026, 1, 8),
                )
            ],
        ]
    )
    universe_session.commit()

    coverage = service.classify(
        universe_session,
        market="IN",
        through_date=as_of_date,
        symbols=("READY.NS", "RECENT.NS"),
    )

    assert coverage.complete_symbols == ("READY.NS",)
    assert coverage.incomplete_symbols == ("RECENT.NS",)
    assert coverage.available_price_date_counts == {
        "READY.NS": 4,
        "RECENT.NS": 3,
    }


def test_breadth_history_price_coverage_counts_observed_warmup_rows(
    universe_session,
) -> None:
    from app.services.breadth_history_price_coverage import (
        BreadthHistoryPriceCoverageService,
    )

    service = BreadthHistoryPriceCoverageService(
        calendar_service=_ObservedWarmupCalendar(),
        lookback_days=2,
        warmup_sessions=2,
    )
    as_of_date = date(2026, 1, 8)

    universe_session.add_all(
        [
            *[
                _price("SUSPENDED.NS", day, 100.0)
                for day in (
                    date(2025, 12, 31),
                    date(2026, 1, 2),
                    date(2026, 1, 6),
                    date(2026, 1, 8),
                )
            ],
            *[
                _price("SHORT.NS", day, 50.0)
                for day in (
                    date(2026, 1, 2),
                    date(2026, 1, 6),
                    date(2026, 1, 8),
                )
            ],
            *[
                _price("NOASOF.NS", day, 25.0)
                for day in (
                    date(2025, 12, 31),
                    date(2026, 1, 2),
                    date(2026, 1, 6),
                )
            ],
        ]
    )
    universe_session.commit()

    coverage = service.classify(
        universe_session,
        market="IN",
        through_date=as_of_date,
        symbols=("SUSPENDED.NS", "SHORT.NS", "NOASOF.NS"),
    )

    assert coverage.complete_symbols == ("SUSPENDED.NS",)
    assert coverage.incomplete_symbols == ("SHORT.NS", "NOASOF.NS")
    assert coverage.history_incomplete_symbols == ("SHORT.NS",)
    assert coverage.missing_through_date_symbols == ("NOASOF.NS",)
    assert coverage.available_price_date_counts == {
        "SUSPENDED.NS": 3,
        "SHORT.NS": 3,
        "NOASOF.NS": 2,
    }


def test_breadth_history_price_coverage_counts_valid_rows_in_database(
    universe_session,
) -> None:
    from app.services.breadth_history_price_coverage import (
        BreadthHistoryPriceCoverageService,
    )

    service = BreadthHistoryPriceCoverageService()
    required_dates = (
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
    )
    universe_session.add_all(
        [_price("FULL.NS", day, 100.0) for day in required_dates]
    )
    universe_session.commit()

    statements: list[str] = []
    engine = universe_session.get_bind()

    def _capture_statement(_conn, _cursor, statement, _params, _context, _many):
        if "stock_prices" in statement:
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", _capture_statement)
    try:
        coverage = service.classify(
            universe_session,
            market="IN",
            through_date=date(2026, 1, 6),
            symbols=("FULL.NS",),
            required_price_dates=required_dates,
        )
    finally:
        event.remove(engine, "before_cursor_execute", _capture_statement)

    assert coverage.complete_symbols == ("FULL.NS",)
    assert any(
        "count(" in statement and "group by" in statement
        for statement in statements
    )
