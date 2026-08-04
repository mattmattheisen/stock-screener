"""Exact OHLCV coverage required to build static breadth history."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock import StockFundamental, StockPrice
from app.services.market_calendar_service import MarketCalendarService


DEFAULT_BREADTH_HISTORY_PRICE_LOOKBACK_DAYS = 220
BREADTH_HISTORY_PRICE_WARMUP_SESSIONS = 69
BREADTH_HISTORY_PRICE_CACHE_LOOKBACK_DAYS = 730


@dataclass(frozen=True)
class BreadthHistoryPriceCoverage:
    complete_symbols: tuple[str, ...]
    incomplete_symbols: tuple[str, ...]
    required_price_date_count: int
    available_price_date_counts: Mapping[str, int]
    history_incomplete_symbols: tuple[str, ...] = ()
    missing_through_date_symbols: tuple[str, ...] = ()
    incomplete_samples: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SymbolPriceCoverage:
    valid_dates: int
    valid_dates_through_oldest_target: int
    latest_date: date | None


@dataclass(frozen=True)
class _RequiredPriceDateWindow:
    price_dates: frozenset[date]
    warmup_start_date: date | None
    warmup_observation_start_date: date | None
    oldest_target_date: date | None


class BreadthHistoryPriceCoverageService:
    """Classify symbols against the exact dates static breadth backfill needs."""

    def __init__(
        self,
        *,
        calendar_service: MarketCalendarService | None = None,
        lookback_days: int = DEFAULT_BREADTH_HISTORY_PRICE_LOOKBACK_DAYS,
        warmup_sessions: int = BREADTH_HISTORY_PRICE_WARMUP_SESSIONS,
        sample_limit: int = 20,
    ) -> None:
        self._calendar_service = calendar_service or MarketCalendarService()
        self._lookback_days = lookback_days
        self._warmup_sessions = warmup_sessions
        self._sample_limit = sample_limit

    def required_price_dates(
        self,
        *,
        market: str,
        through_date: date,
    ) -> frozenset[date]:
        return self._required_price_date_window(
            market=market,
            through_date=through_date,
        ).price_dates

    def _required_price_date_window(
        self,
        *,
        market: str,
        through_date: date,
    ) -> _RequiredPriceDateWindow:
        normalized_market = str(market or "").strip().upper()
        target_start = through_date - timedelta(days=self._lookback_days)
        target_dates = self._calendar_service.trading_days(
            normalized_market,
            target_start,
            through_date,
        )
        if not target_dates:
            return _RequiredPriceDateWindow(
                price_dates=frozenset(),
                warmup_start_date=None,
                warmup_observation_start_date=None,
                oldest_target_date=None,
            )

        oldest_target_date = target_dates[0]
        if self._warmup_sessions <= 0:
            warmup_start = oldest_target_date
        else:
            anchors = self._calendar_service.session_anchors(
                normalized_market,
                oldest_target_date,
                offsets=(self._warmup_sessions,),
            )
            warmup_start = anchors[self._warmup_sessions]

        return _RequiredPriceDateWindow(
            price_dates=frozenset(
                self._calendar_service.trading_days(
                    normalized_market,
                    warmup_start,
                    through_date,
                )
            ),
            warmup_start_date=warmup_start,
            warmup_observation_start_date=(
                through_date - timedelta(days=BREADTH_HISTORY_PRICE_CACHE_LOOKBACK_DAYS)
            ),
            oldest_target_date=oldest_target_date,
        )

    def classify(
        self,
        db: Session,
        *,
        market: str,
        through_date: date,
        symbols: Sequence[str],
        required_price_dates: Collection[date] | None = None,
    ) -> BreadthHistoryPriceCoverage:
        normalized_symbols = tuple(
            dict.fromkeys(str(symbol or "").strip().upper() for symbol in symbols)
        )
        normalized_symbols = tuple(symbol for symbol in normalized_symbols if symbol)
        if required_price_dates is None:
            price_date_window = self._required_price_date_window(
                market=market,
                through_date=through_date,
            )
            price_dates = price_date_window.price_dates
            warmup_start_date = price_date_window.warmup_start_date
            warmup_observation_start_date = (
                price_date_window.warmup_observation_start_date
            )
            oldest_target_date = price_date_window.oldest_target_date
        else:
            price_dates = frozenset(required_price_dates)
            warmup_start_date = None
            warmup_observation_start_date = None
            oldest_target_date = None

        if not price_dates:
            return BreadthHistoryPriceCoverage(
                complete_symbols=normalized_symbols,
                incomplete_symbols=(),
                required_price_date_count=0,
                available_price_date_counts={},
            )

        coverage_by_symbol = self._available_price_coverage(
            db,
            symbols=normalized_symbols,
            required_price_dates=price_dates,
            oldest_target_date=oldest_target_date,
            warmup_observation_start_date=warmup_observation_start_date,
        )
        required_count = len(price_dates)
        required_count_through_oldest_target = (
            sum(1 for day in price_dates if day <= oldest_target_date)
            if oldest_target_date is not None
            else required_count
        )
        minimum_observations = min(
            required_count_through_oldest_target,
            max(1, self._warmup_sessions + 1),
        )
        default_coverage = _SymbolPriceCoverage(
            valid_dates=0,
            valid_dates_through_oldest_target=0,
            latest_date=None,
        )
        ipo_dates = (
            self._ipo_dates(db, normalized_symbols)
            if warmup_start_date is not None and oldest_target_date is not None
            else {}
        )
        available_counts = {
            symbol: coverage_by_symbol.get(symbol, default_coverage).valid_dates
            for symbol in normalized_symbols
        }
        history_incomplete = []
        missing_through_date = []
        for symbol in normalized_symbols:
            coverage = coverage_by_symbol.get(symbol, default_coverage)
            has_required_observations = self._has_required_observations(
                coverage,
                minimum_observations=minimum_observations,
                warmup_start_date=warmup_start_date,
                oldest_target_date=oldest_target_date,
                ipo_date=ipo_dates.get(symbol),
            )
            if not has_required_observations:
                history_incomplete.append(symbol)
            elif coverage.latest_date != through_date:
                missing_through_date.append(symbol)

        incomplete_symbol_set = {*history_incomplete, *missing_through_date}
        incomplete = tuple(
            symbol for symbol in normalized_symbols if symbol in incomplete_symbol_set
        )
        incomplete_set = set(incomplete)
        return BreadthHistoryPriceCoverage(
            complete_symbols=tuple(
                symbol for symbol in normalized_symbols if symbol not in incomplete_set
            ),
            incomplete_symbols=incomplete,
            required_price_date_count=required_count,
            available_price_date_counts=available_counts,
            history_incomplete_symbols=tuple(history_incomplete),
            missing_through_date_symbols=tuple(missing_through_date),
            incomplete_samples=incomplete[: self._sample_limit],
        )

    @staticmethod
    def _finite_ohlc_filters():
        finite_upper = float("inf")
        finite_lower = float("-inf")
        return (
            StockPrice.open.isnot(None),
            StockPrice.high.isnot(None),
            StockPrice.low.isnot(None),
            StockPrice.close.isnot(None),
            StockPrice.open > finite_lower,
            StockPrice.open < finite_upper,
            StockPrice.high > finite_lower,
            StockPrice.high < finite_upper,
            StockPrice.low > finite_lower,
            StockPrice.low < finite_upper,
            StockPrice.close > finite_lower,
            StockPrice.close < finite_upper,
        )

    @classmethod
    def _available_price_coverage(
        cls,
        db: Session,
        *,
        symbols: Sequence[str],
        required_price_dates: Collection[date],
        oldest_target_date: date | None,
        warmup_observation_start_date: date | None,
    ) -> dict[str, _SymbolPriceCoverage]:
        coverage_by_symbol: dict[str, _SymbolPriceCoverage] = {}
        default_coverage = _SymbolPriceCoverage(
            valid_dates=0,
            valid_dates_through_oldest_target=0,
            latest_date=None,
        )
        for chunk_start in range(0, len(symbols), 500):
            chunk_symbols = symbols[chunk_start : chunk_start + 500]
            rows = (
                db.query(
                    StockPrice.symbol,
                    func.count(StockPrice.date),
                    func.max(StockPrice.date),
                )
                .filter(
                    StockPrice.symbol.in_(chunk_symbols),
                    StockPrice.date.in_(required_price_dates),
                    *cls._finite_ohlc_filters(),
                )
                .group_by(StockPrice.symbol)
                .all()
            )
            for symbol, valid_dates, latest_date in rows:
                valid_required_dates = int(valid_dates or 0)
                coverage_by_symbol[str(symbol).upper()] = _SymbolPriceCoverage(
                    valid_dates=valid_required_dates,
                    valid_dates_through_oldest_target=(
                        valid_required_dates
                        if oldest_target_date is None
                        else 0
                    ),
                    latest_date=latest_date,
                )
            if oldest_target_date is None:
                continue

            warmup_filters = [
                StockPrice.symbol.in_(chunk_symbols),
                StockPrice.date <= oldest_target_date,
                *cls._finite_ohlc_filters(),
            ]
            if warmup_observation_start_date is not None:
                warmup_filters.append(
                    StockPrice.date >= warmup_observation_start_date
                )
            warmup_rows = (
                db.query(
                    StockPrice.symbol,
                    func.count(StockPrice.date),
                )
                .filter(*warmup_filters)
                .group_by(StockPrice.symbol)
                .all()
            )
            for symbol, warmup_valid_dates in warmup_rows:
                key = str(symbol).upper()
                existing = coverage_by_symbol.get(key, default_coverage)
                coverage_by_symbol[key] = _SymbolPriceCoverage(
                    valid_dates=existing.valid_dates,
                    valid_dates_through_oldest_target=int(
                        warmup_valid_dates or 0
                    ),
                    latest_date=existing.latest_date,
                )
        return coverage_by_symbol

    @staticmethod
    def _has_required_observations(
        coverage: _SymbolPriceCoverage,
        *,
        minimum_observations: int,
        warmup_start_date: date | None,
        oldest_target_date: date | None,
        ipo_date: date | None,
    ) -> bool:
        if oldest_target_date is None:
            return coverage.valid_dates >= minimum_observations
        if coverage.valid_dates_through_oldest_target >= minimum_observations:
            return True
        if ipo_date is None or warmup_start_date is None:
            return False
        if ipo_date <= warmup_start_date:
            return False
        return coverage.valid_dates >= minimum_observations

    @staticmethod
    def _ipo_dates(db: Session, symbols: Sequence[str]) -> dict[str, date]:
        ipo_dates: dict[str, date] = {}
        for chunk_start in range(0, len(symbols), 500):
            chunk_symbols = symbols[chunk_start : chunk_start + 500]
            rows = (
                db.query(StockFundamental.symbol, StockFundamental.ipo_date)
                .filter(
                    StockFundamental.symbol.in_(chunk_symbols),
                    StockFundamental.ipo_date.isnot(None),
                )
                .all()
            )
            for symbol, ipo_date in rows:
                ipo_dates[str(symbol).upper()] = ipo_date
        return ipo_dates


__all__ = [
    "BREADTH_HISTORY_PRICE_WARMUP_SESSIONS",
    "BreadthHistoryPriceCoverage",
    "BreadthHistoryPriceCoverageService",
    "DEFAULT_BREADTH_HISTORY_PRICE_LOOKBACK_DAYS",
]
