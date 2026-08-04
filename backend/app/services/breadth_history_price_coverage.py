"""Exact OHLCV coverage required to build static breadth history."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.stock import StockPrice
from app.services.market_calendar_service import MarketCalendarService
from app.services.price_row_normalization import finite_ohlc_values


DEFAULT_BREADTH_HISTORY_PRICE_LOOKBACK_DAYS = 220
BREADTH_HISTORY_PRICE_WARMUP_SESSIONS = 69


@dataclass(frozen=True)
class BreadthHistoryPriceCoverage:
    complete_symbols: tuple[str, ...]
    incomplete_symbols: tuple[str, ...]
    required_price_date_count: int
    available_price_date_counts: Mapping[str, int]
    incomplete_samples: tuple[str, ...] = ()


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

        available_by_symbol = self._available_price_dates(
            db,
            symbols=normalized_symbols,
            required_price_dates=price_dates,
        )
        required_count = len(price_dates)
        available_counts = {
            symbol: len(available_by_symbol.get(symbol, set()))
            for symbol in normalized_symbols
        }
        incomplete = tuple(
            symbol
            for symbol in normalized_symbols
            if available_counts[symbol] < required_count
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
    def _available_price_dates(
        db: Session,
        *,
        symbols: Sequence[str],
        required_price_dates: Collection[date],
    ) -> dict[str, set[date]]:
        available_by_symbol: dict[str, set[date]] = {}
        for chunk_start in range(0, len(symbols), 500):
            chunk_symbols = symbols[chunk_start : chunk_start + 500]
            rows = (
                db.query(
                    StockPrice.symbol,
                    StockPrice.date,
                    StockPrice.open,
                    StockPrice.high,
                    StockPrice.low,
                    StockPrice.close,
                )
                .filter(
                    StockPrice.symbol.in_(chunk_symbols),
                    StockPrice.date.in_(required_price_dates),
                )
                .all()
            )
            for symbol, row_date, open_, high, low, close in rows:
                if row_date is None:
                    continue
                if finite_ohlc_values(open_, high, low, close) is None:
                    continue
                available_by_symbol.setdefault(str(symbol).upper(), set()).add(
                    row_date
                )
        return available_by_symbol


__all__ = [
    "BREADTH_HISTORY_PRICE_WARMUP_SESSIONS",
    "BreadthHistoryPriceCoverage",
    "BreadthHistoryPriceCoverageService",
    "DEFAULT_BREADTH_HISTORY_PRICE_LOOKBACK_DAYS",
]
