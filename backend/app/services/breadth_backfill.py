"""Typed planning and execution boundary for historical breadth backfills."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ..domain.providers.price_symbol_support import split_supported_price_symbols
from ..models.stock_universe import StockUniverse
from .breadth.engine import BreadthEngineRequest
from .breadth.types import BreadthUniverseMember, BreadthUniverseSnapshot
from .breadth_coverage import (
    BreadthCoverageReport,
    BreadthOutcomeCounter,
    BreadthOutcomeReport,
    BreadthPriceCoverageAccumulator,
)
from .derived_data_execution_policy import DerivedDataExecutionPolicy
from .fx_service import default_currency_for_market
from .point_in_time_universe_service import hash_point_in_time_universe_symbols
from .static_breadth_eligibility import static_breadth_eligibility_signature

if TYPE_CHECKING:
    from .breadth_calculator_service import BreadthCalculatorService


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BreadthEligibleUniverse:
    """The exact eligible universe and provenance for one calculation date."""

    calculation_date: date
    symbols: tuple[str, ...]
    eligibility_signature: str


@dataclass(frozen=True, slots=True)
class BreadthBackfillPlan:
    """Validated dates and optional explicit universes for one backfill."""

    dates: tuple[date, ...]
    universes: Mapping[date, BreadthEligibleUniverse] | None = None

    @classmethod
    def from_legacy(
        cls,
        *,
        dates: Sequence[date],
        eligible_symbols_by_date: Mapping[date, Sequence[str]] | None,
        eligibility_signatures_by_date: Mapping[date, str] | None,
    ) -> BreadthBackfillPlan:
        ordered_dates = tuple(sorted(set(dates)))
        has_symbols = eligible_symbols_by_date is not None
        has_signatures = eligibility_signatures_by_date is not None
        if has_symbols != has_signatures:
            raise ValueError(
                "eligible symbols and eligibility signatures must be supplied together"
            )
        if not has_symbols:
            return cls(dates=ordered_dates)

        assert eligible_symbols_by_date is not None
        assert eligibility_signatures_by_date is not None
        universes: dict[date, BreadthEligibleUniverse] = {}
        for calculation_date in ordered_dates:
            if calculation_date not in eligible_symbols_by_date:
                raise ValueError(
                    "eligible symbols missing for "
                    f"{calculation_date.isoformat()}"
                )
            if calculation_date not in eligibility_signatures_by_date:
                raise ValueError(
                    "eligibility signature missing for "
                    f"{calculation_date.isoformat()}"
                )
            symbols = tuple(
                sorted(set(eligible_symbols_by_date[calculation_date]))
            )
            expected_signature = static_breadth_eligibility_signature(symbols)
            supplied_signature = eligibility_signatures_by_date[calculation_date]
            if supplied_signature != expected_signature:
                raise ValueError(
                    "eligibility signature does not match canonical symbols for "
                    f"{calculation_date.isoformat()}"
                )
            universes[calculation_date] = BreadthEligibleUniverse(
                calculation_date=calculation_date,
                symbols=symbols,
                eligibility_signature=expected_signature,
            )
        return cls(
            dates=ordered_dates,
            universes=MappingProxyType(universes),
        )

    def universe_for(
        self,
        calculation_date: date,
    ) -> BreadthEligibleUniverse | None:
        if self.universes is None:
            return None
        return self.universes[calculation_date]


@dataclass(frozen=True, slots=True)
class BreadthBackfillResult:
    values: Mapping[str, Any]

    def to_legacy_dict(self) -> dict[str, Any]:
        return dict(self.values)


class BreadthBackfillExecutor:
    """Execute one validated historical breadth plan."""

    def __init__(self, calculator: BreadthCalculatorService) -> None:
        self._calculator = calculator

    def execute(
        self,
        plan: BreadthBackfillPlan,
        *,
        policy: DerivedDataExecutionPolicy,
        exclude_unsupported_price_symbols: bool = False,
        required_as_of_date: date | None = None,
    ) -> BreadthBackfillResult:
        return self._execute_canonical(
            plan,
            policy=policy,
            exclude_unsupported_price_symbols=exclude_unsupported_price_symbols,
            required_as_of_date=required_as_of_date,
        )

    def _execute_canonical(
        self,
        plan: BreadthBackfillPlan,
        *,
        policy: DerivedDataExecutionPolicy,
        exclude_unsupported_price_symbols: bool,
        required_as_of_date: date | None,
    ) -> BreadthBackfillResult:
        calculator = self._calculator
        ordered_dates = list(plan.dates)
        started_at = datetime.now(UTC)
        explicit_symbols = (
            {
                calculation_date: plan.universe_for(calculation_date).symbols
                for calculation_date in ordered_dates
            }
            if plan.universes is not None
            else None
        )

        if explicit_symbols is None:
            stock_rows = (
                calculator.db.query(StockUniverse)
                .filter(
                    StockUniverse.is_active == True,
                    StockUniverse.market == calculator.market,
                )
                .all()
            )
            rows_by_symbol = {row.symbol: row for row in stock_rows}
            target_symbols = sorted(rows_by_symbol)
            symbols_by_date = {
                calculation_date: tuple(target_symbols)
                for calculation_date in ordered_dates
            }
        else:
            target_symbols = sorted(
                {
                    symbol
                    for symbols in explicit_symbols.values()
                    for symbol in symbols
                }
            )
            stock_rows = (
                calculator.db.query(StockUniverse)
                .filter(StockUniverse.symbol.in_(target_symbols))
                .all()
                if target_symbols
                else []
            )
            rows_by_symbol = {row.symbol: row for row in stock_rows}
            symbols_by_date = dict(explicit_symbols)

        skipped_unsupported_symbols: list[str] = []
        if exclude_unsupported_price_symbols:
            target_symbols, skipped_unsupported_symbols = split_supported_price_symbols(
                target_symbols
            )
            supported = set(target_symbols)
            symbols_by_date = {
                calculation_date: tuple(
                    symbol for symbol in symbols if symbol in supported
                )
                for calculation_date, symbols in symbols_by_date.items()
            }

        currency_by_symbol = {
            symbol: (
                getattr(rows_by_symbol.get(symbol), "currency", None)
                or default_currency_for_market(calculator.market)
            )
            for symbol in target_symbols
        }
        universes_by_date: dict[date, BreadthUniverseSnapshot] = {}
        for calculation_date in ordered_dates:
            symbols = tuple(sorted(symbols_by_date[calculation_date]))
            supplied = plan.universe_for(calculation_date)
            signature = (
                supplied.eligibility_signature
                if supplied is not None
                else hash_point_in_time_universe_symbols(symbols)
            )
            universes_by_date[calculation_date] = BreadthUniverseSnapshot(
                calculation_date=calculation_date,
                members=tuple(
                    BreadthUniverseMember(symbol, currency_by_symbol[symbol])
                    for symbol in symbols
                ),
                broad_signature=signature,
            )

        prices_by_symbol: dict[str, Any] = {}
        price_coverage = BreadthPriceCoverageAccumulator()
        for offset in range(0, len(target_symbols), 500):
            batch_symbols = target_symbols[offset : offset + 500]
            if required_as_of_date is not None and explicit_symbols is not None:
                grouped: dict[date, list[str]] = {}
                for symbol in batch_symbols:
                    symbol_date = max(
                        calculation_date
                        for calculation_date in ordered_dates
                        if symbol in symbols_by_date[calculation_date]
                    )
                    grouped.setdefault(symbol_date, []).append(symbol)
                loaded: dict[str, Any] = {}
                cache_misses: list[str] = []
                for symbol_date, symbols in grouped.items():
                    group_prices, group_misses = calculator._load_price_data_for_batch(
                        batch_symbols=symbols,
                        cache_only=policy.cache_only,
                        required_as_of_date=symbol_date,
                    )
                    loaded.update(group_prices)
                    cache_misses.extend(group_misses)
            else:
                kwargs = (
                    {"required_as_of_date": required_as_of_date}
                    if required_as_of_date is not None
                    else {}
                )
                loaded, cache_misses = calculator._load_price_data_for_batch(
                    batch_symbols=batch_symbols,
                    cache_only=policy.cache_only,
                    **kwargs,
                )
            price_coverage.record_batch(batch_symbols, cache_misses)
            for symbol, history in loaded.items():
                if history is not None and not history.empty:
                    prices_by_symbol[symbol] = history

        outcomes_by_date = {
            calculation_date: BreadthOutcomeCounter()
            for calculation_date in ordered_dates
        }
        required_columns = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        for calculation_date in ordered_dates:
            for symbol in symbols_by_date[calculation_date]:
                history = prices_by_symbol.get(symbol)
                if history is None or history.empty:
                    outcomes_by_date[calculation_date].record_cache_miss()
                elif not required_columns.issubset(history.columns):
                    outcomes_by_date[calculation_date].record_error()
                    prices_by_symbol.pop(symbol, None)
                elif calculator._has_exact_advance_decline_session(
                    history,
                    calculation_date,
                ):
                    outcomes_by_date[calculation_date].record_scanned()
                else:
                    outcomes_by_date[calculation_date].record_insufficient()

        all_members = tuple(
            BreadthUniverseMember(symbol, currency_by_symbol[symbol])
            for symbol in target_symbols
        )
        fx_by_currency = calculator._load_fx_for_prices(
            all_members,
            prices_by_symbol,
        )
        canonical_by_date = calculator.engine.calculate(
            BreadthEngineRequest(
                market=calculator.market,
                dates=tuple(ordered_dates),
                universes_by_date=universes_by_date,
                prices_by_symbol=prices_by_symbol,
                fx_by_currency=fx_by_currency,
                seed_counts=calculator._load_ratio_context_counts(ordered_dates),
            )
        )

        processed_dates = [
            calculation_date
            for calculation_date in ordered_dates
            if outcomes_by_date[calculation_date].report().scanned > 0
        ]
        error_dates = [
            calculation_date.isoformat()
            for calculation_date in ordered_dates
            if calculation_date not in processed_dates
        ]
        if processed_dates:
            elapsed = (datetime.now(UTC) - started_at).total_seconds()
            duration = round(elapsed / len(processed_dates), 2)
            calculator.persistence.upsert_many(
                (canonical_by_date[value] for value in processed_dates),
                duration_seconds_by_date={value: duration for value in processed_dates},
            )

        result: dict[str, Any] = {
            "total_dates": len(ordered_dates),
            "processed": len(processed_dates),
            "errors": len(error_dates),
            "error_dates": error_dates,
        }
        if explicit_symbols is not None:
            result.update(
                {
                    "eligible_stocks_by_date": {
                        value.isoformat(): len(symbols_by_date[value])
                        for value in ordered_dates
                    },
                    "scanned_stocks_by_date": {
                        value.isoformat(): outcomes_by_date[value].report().scanned
                        for value in ordered_dates
                    },
                    "calculation_errors_by_date": {
                        value.isoformat(): outcomes_by_date[value].report().errors
                        for value in ordered_dates
                    },
                }
            )
        if exclude_unsupported_price_symbols:
            result.update(
                {
                    "skipped_unsupported_symbols": len(
                        skipped_unsupported_symbols
                    ),
                    "unsupported_symbols_sample": sorted(
                        set(skipped_unsupported_symbols)
                    )[:20],
                }
            )
        if policy.cache_only:
            aggregate = sum(
                (counter.report() for counter in outcomes_by_date.values()),
                start=BreadthOutcomeReport(),
            )
            result.update(
                BreadthCoverageReport.from_parts(
                    price_coverage.report(),
                    aggregate,
                ).to_backfill_dict()
            )
        return BreadthBackfillResult(MappingProxyType(result))
