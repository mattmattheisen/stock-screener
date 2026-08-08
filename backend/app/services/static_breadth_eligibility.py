"""Date-specific, cache-only eligibility for static breadth calculations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import math
import hashlib
from types import MappingProxyType

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.providers.price_symbol_support import split_supported_price_symbols
from ..models.stock import StockPrice
from .bounded_history_universe import CurrentActiveFallbackUniverseResolver


MINIMUM_BREADTH_OBSERVATIONS = 70
STATIC_BREADTH_ELIGIBILITY_VERSION = "exact-ohlc-70-v1"
DEFAULT_EXCLUSION_SAMPLE_LIMIT = 20
PRICE_QUERY_CHUNK_SIZE = 500


@dataclass(frozen=True, slots=True)
class StaticBreadthEligibility:
    eligible_symbols_by_date: Mapping[date, tuple[str, ...]]
    candidate_counts_by_date: Mapping[date, int]
    eligible_counts_by_date: Mapping[date, int]
    universe_policy_by_date: Mapping[date, str]
    eligibility_signatures_by_date: Mapping[date, str]
    unsupported_count: int
    insufficient_history_count: int
    exact_date_gap_count: int
    unsupported_symbols: tuple[str, ...]
    insufficient_history_symbols: tuple[str, ...]
    exact_date_gap_symbols: tuple[str, ...]


def _valid_ohlc_predicate():
    predicates = []
    for column in (StockPrice.open, StockPrice.high, StockPrice.low, StockPrice.close):
        predicates.extend(
            (column.is_not(None), column < math.inf, column > -math.inf)
        )
    return tuple(predicates)


def _bounded_sample(symbols: set[str], limit: int) -> tuple[str, ...]:
    return tuple(sorted(symbols)[:limit])


def static_breadth_eligibility_signature(symbols: Sequence[str]) -> str:
    payload = "".join(
        (f"{STATIC_BREADTH_ELIGIBILITY_VERSION}\n", *(f"{symbol}\n" for symbol in symbols))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify_static_breadth_eligibility(
    db: Session,
    *,
    market: str,
    calculation_dates: Sequence[date],
    universe_resolver: CurrentActiveFallbackUniverseResolver | None = None,
    exclusion_sample_limit: int = DEFAULT_EXCLUSION_SAMPLE_LIMIT,
) -> StaticBreadthEligibility:
    """Classify eligible symbols using only persisted universe and OHLC data."""
    if exclusion_sample_limit < 0:
        raise ValueError("exclusion_sample_limit must be non-negative")
    normalized_market = str(market or "").strip().upper()
    ordered_dates = tuple(sorted(set(calculation_dates)))
    resolver = universe_resolver or CurrentActiveFallbackUniverseResolver()

    candidates_by_date: dict[date, tuple[str, ...]] = {}
    supported_by_date: dict[date, tuple[str, ...]] = {}
    policy_by_date: dict[date, str] = {}
    unsupported: set[str] = set()
    for calculation_date in ordered_dates:
        universe = resolver.resolve(
            db,
            market=normalized_market,
            as_of_date=calculation_date,
        )
        candidates = tuple(sorted(set(universe.symbols)))
        supported, unsupported_for_date = split_supported_price_symbols(candidates)
        candidates_by_date[calculation_date] = candidates
        supported_by_date[calculation_date] = tuple(supported)
        unsupported.update(unsupported_for_date)
        policy_by_date[calculation_date] = (
            resolver.policy_for(normalized_market, calculation_date) or "unrecorded"
        )

    eligible_by_date: dict[date, tuple[str, ...]] = {}
    insufficient: set[str] = set()
    exact_date_gaps: set[str] = set()
    for calculation_date in ordered_dates:
        supported_symbols = supported_by_date[calculation_date]
        valid_counts: dict[str, int] = {}
        exact_symbols: set[str] = set()
        for offset in range(0, len(supported_symbols), PRICE_QUERY_CHUNK_SIZE):
            chunk = supported_symbols[offset : offset + PRICE_QUERY_CHUNK_SIZE]
            count_rows = (
                db.query(StockPrice.symbol, func.count(StockPrice.id))
                .filter(
                    StockPrice.symbol.in_(chunk),
                    StockPrice.date <= calculation_date,
                    *_valid_ohlc_predicate(),
                )
                .group_by(StockPrice.symbol)
                .all()
            )
            valid_counts.update(
                {symbol: int(count) for symbol, count in count_rows}
            )
            exact_symbols.update(
                symbol
                for (symbol,) in db.query(StockPrice.symbol)
                .filter(
                    StockPrice.symbol.in_(chunk),
                    StockPrice.date == calculation_date,
                    *_valid_ohlc_predicate(),
                )
                .all()
            )
        eligible: list[str] = []
        for symbol in supported_symbols:
            if symbol not in exact_symbols:
                exact_date_gaps.add(symbol)
            observation_count = valid_counts.get(symbol, 0)
            if observation_count < MINIMUM_BREADTH_OBSERVATIONS:
                insufficient.add(symbol)
            if (
                symbol in exact_symbols
                and observation_count >= MINIMUM_BREADTH_OBSERVATIONS
            ):
                eligible.append(symbol)
        eligible_by_date[calculation_date] = tuple(eligible)

    eligible_counts = {
        calculation_date: len(symbols)
        for calculation_date, symbols in eligible_by_date.items()
    }
    return StaticBreadthEligibility(
        eligible_symbols_by_date=MappingProxyType(eligible_by_date),
        candidate_counts_by_date=MappingProxyType(
            {
                calculation_date: len(symbols)
                for calculation_date, symbols in candidates_by_date.items()
            }
        ),
        eligible_counts_by_date=MappingProxyType(eligible_counts),
        universe_policy_by_date=MappingProxyType(policy_by_date),
        eligibility_signatures_by_date=MappingProxyType(
            {
                calculation_date: static_breadth_eligibility_signature(symbols)
                for calculation_date, symbols in eligible_by_date.items()
            }
        ),
        unsupported_count=len(unsupported),
        insufficient_history_count=len(insufficient),
        exact_date_gap_count=len(exact_date_gaps),
        unsupported_symbols=_bounded_sample(unsupported, exclusion_sample_limit),
        insufficient_history_symbols=_bounded_sample(
            insufficient, exclusion_sample_limit
        ),
        exact_date_gap_symbols=_bounded_sample(
            exact_date_gaps, exclusion_sample_limit
        ),
    )
