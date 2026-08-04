"""Exact OHLCV coverage required to build static breadth history."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock import StockPrice
from app.services.market_calendar_service import MarketCalendarService


DEFAULT_BREADTH_HISTORY_PRICE_LOOKBACK_DAYS = 220
BREADTH_HISTORY_PRICE_WARMUP_SESSIONS = 69


@dataclass(frozen=True)
class BreadthHistoryPriceCoverage:
    complete_symbols: tuple[str, ...]
    incomplete_symbols: tuple[str, ...]
    required_price_date_count: int
    available_price_date_counts: Mapping[str, int]
    incomplete_samples: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SymbolPriceCoverage:
    valid_dates: int
    latest_date: date | None


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
        normalized_market = str(market or "").strip().upper()
        target_start = through_date - timedelta(days=self._lookback_days)
        target_dates = self._calendar_service.trading_days(
            normalized_market,
            target_start,
            through_date,
        )
        if not target_dates:
            return frozenset()

        if self._warmup_sessions <= 0:
            warmup_start = target_dates[0]
        else:
            anchors = self._calendar_service.session_anchors(
                normalized_market,
                target_dates[0],
                offsets=(self._warmup_sessions,),
            )
            warmup_start = anchors[self._warmup_sessions]

        return frozenset(
            self._calendar_service.trading_days(
                normalized_market,
                warmup_start,
                through_date,
            )
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
        price_dates = frozenset(
            required_price_dates
            if required_price_dates is not None
            else self.required_price_dates(
                market=market,
                through_date=through_date,
            )
        )
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
        )
        required_count = len(price_dates)
        minimum_observations = min(
            required_count,
            max(1, self._warmup_sessions + 1),
        )
        available_counts = {
            symbol: coverage_by_symbol.get(
                symbol,
                _SymbolPriceCoverage(valid_dates=0, latest_date=None),
            ).valid_dates
            for symbol in normalized_symbols
        }
        incomplete = tuple(
            symbol
            for symbol in normalized_symbols
            if (
                available_counts[symbol] < minimum_observations
                or coverage_by_symbol.get(
                    symbol,
                    _SymbolPriceCoverage(valid_dates=0, latest_date=None),
                ).latest_date
                != through_date
            )
        )
        incomplete_set = set(incomplete)
        return BreadthHistoryPriceCoverage(
            complete_symbols=tuple(
                symbol for symbol in normalized_symbols if symbol not in incomplete_set
            ),
            incomplete_symbols=incomplete,
            required_price_date_count=required_count,
            available_price_date_counts=available_counts,
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
    ) -> dict[str, _SymbolPriceCoverage]:
        coverage_by_symbol: dict[str, _SymbolPriceCoverage] = {}
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
                coverage_by_symbol[str(symbol).upper()] = _SymbolPriceCoverage(
                    valid_dates=int(valid_dates or 0),
                    latest_date=latest_date,
                )
        return coverage_by_symbol


__all__ = [
    "BREADTH_HISTORY_PRICE_WARMUP_SESSIONS",
    "BreadthHistoryPriceCoverage",
    "BreadthHistoryPriceCoverageService",
    "DEFAULT_BREADTH_HISTORY_PRICE_LOOKBACK_DAYS",
]
