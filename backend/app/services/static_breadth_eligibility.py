"""Date-specific, cache-only eligibility for static breadth calculations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import math
from types import MappingProxyType

from sqlalchemy.orm import Session

from ..domain.providers.price_symbol_support import split_supported_price_symbols
from ..models.stock import StockPrice
from .bounded_history_universe import CurrentActiveFallbackUniverseResolver


MINIMUM_BREADTH_OBSERVATIONS = 70
DEFAULT_EXCLUSION_SAMPLE_LIMIT = 20
PRICE_QUERY_CHUNK_SIZE = 500


@dataclass(frozen=True, slots=True)
class StaticBreadthEligibility:
    eligible_symbols_by_date: Mapping[date, tuple[str, ...]]
    candidate_counts_by_date: Mapping[date, int]
    eligible_counts_by_date: Mapping[date, int]
    universe_policy_by_date: Mapping[date, str]
    unsupported_symbols: tuple[str, ...]
    insufficient_history_symbols: tuple[str, ...]
    exact_date_gap_symbols: tuple[str, ...]


def _valid_ohlc(row: StockPrice) -> bool:
    values = (row.open, row.high, row.low, row.close)
    return all(
        value is not None and math.isfinite(float(value))
        for value in values
    )


def _bounded_sample(symbols: set[str], limit: int) -> tuple[str, ...]:
    return tuple(sorted(symbols)[:limit])


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

    union_symbols = sorted(
        {
            symbol
            for symbols in supported_by_date.values()
            for symbol in symbols
        }
    )
    valid_dates_by_symbol: dict[str, set[date]] = defaultdict(set)
    if ordered_dates:
        latest_date = ordered_dates[-1]
        for offset in range(0, len(union_symbols), PRICE_QUERY_CHUNK_SIZE):
            chunk = union_symbols[offset : offset + PRICE_QUERY_CHUNK_SIZE]
            if not chunk:
                continue
            rows = (
                db.query(StockPrice)
                .filter(
                    StockPrice.symbol.in_(chunk),
                    StockPrice.date <= latest_date,
                )
                .all()
            )
            for row in rows:
                if _valid_ohlc(row):
                    valid_dates_by_symbol[row.symbol].add(row.date)

    eligible_by_date: dict[date, tuple[str, ...]] = {}
    insufficient: set[str] = set()
    exact_date_gaps: set[str] = set()
    for calculation_date in ordered_dates:
        eligible: list[str] = []
        for symbol in supported_by_date[calculation_date]:
            valid_dates = valid_dates_by_symbol.get(symbol, set())
            if calculation_date not in valid_dates:
                exact_date_gaps.add(symbol)
            observation_count = sum(
                observed_date <= calculation_date for observed_date in valid_dates
            )
            if observation_count < MINIMUM_BREADTH_OBSERVATIONS:
                insufficient.add(symbol)
            if (
                calculation_date in valid_dates
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
        unsupported_symbols=_bounded_sample(unsupported, exclusion_sample_limit),
        insufficient_history_symbols=_bounded_sample(
            insufficient, exclusion_sample_limit
        ),
        exact_date_gap_symbols=_bounded_sample(
            exact_date_gaps, exclusion_sample_limit
        ),
    )
