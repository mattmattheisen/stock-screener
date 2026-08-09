"""Typed planning and execution boundary for historical breadth backfills."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ..domain.providers.price_symbol_support import split_supported_price_symbols
from ..models.stock_universe import StockUniverse
from .breadth_coverage import (
    BreadthCoverageReport,
    BreadthOutcomeCounter,
    BreadthOutcomeReport,
    BreadthPriceCoverageAccumulator,
)
from .derived_data_execution_policy import DerivedDataExecutionPolicy

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
    ) -> "BreadthBackfillPlan":
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

    def __init__(self, calculator: "BreadthCalculatorService") -> None:
        self._calculator = calculator

    def execute(
        self,
        plan: BreadthBackfillPlan,
        *,
        policy: DerivedDataExecutionPolicy,
        exclude_unsupported_price_symbols: bool = False,
        required_as_of_date: date | None = None,
    ) -> BreadthBackfillResult:
        calculator = self._calculator
        ordered_dates = list(plan.dates)
        start_time = datetime.now()
        explicit_eligible_symbols = (
            {
                calculation_date: plan.universe_for(calculation_date).symbols
                for calculation_date in ordered_dates
            }
            if plan.universes is not None
            else None
        )
        if explicit_eligible_symbols is not None:
            target_symbols = sorted(
                {
                    symbol
                    for symbols in explicit_eligible_symbols.values()
                    for symbol in symbols
                }
            )
        else:
            active_stocks = calculator.db.query(StockUniverse).filter(
                StockUniverse.is_active == True,
                StockUniverse.market == calculator.market,
            ).all()
            target_symbols = [stock.symbol for stock in active_stocks]
        skipped_unsupported_symbols: list[str] = []
        if exclude_unsupported_price_symbols:
            supported_symbols, skipped_unsupported_symbols = split_supported_price_symbols(
                target_symbols
            )
            target_symbols = supported_symbols
            if explicit_eligible_symbols is not None:
                supported_symbol_set = set(supported_symbols)
                explicit_eligible_symbols = {
                    calculation_date: tuple(
                        symbol
                        for symbol in symbols
                        if symbol in supported_symbol_set
                    )
                    for calculation_date, symbols in explicit_eligible_symbols.items()
                }
        explicit_eligible_symbol_sets = (
            {
                calculation_date: set(symbols)
                for calculation_date, symbols in explicit_eligible_symbols.items()
            }
            if explicit_eligible_symbols is not None
            else None
        )
        logger.info(
            "Backfilling breadth for %s trading days across %s active stocks",
            len(ordered_dates),
            len(target_symbols),
        )
        if skipped_unsupported_symbols:
            logger.info(
                "Skipping %s unsupported Yahoo price symbols in breadth backfill",
                len(skipped_unsupported_symbols),
            )

        metrics_by_date = {calc_date: calculator._empty_metrics() for calc_date in ordered_dates}
        if plan.universes is not None:
            for calculation_date in ordered_dates:
                universe = plan.universe_for(calculation_date)
                assert universe is not None
                metrics_by_date[calculation_date]["eligibility_signature"] = (
                    universe.eligibility_signature
                )
        outcomes_by_date = {
            calc_date: BreadthOutcomeCounter()
            for calc_date in ordered_dates
        }
        price_coverage = BreadthPriceCoverageAccumulator()
        batch_size = 500
        total_stocks = len(target_symbols)

        for i in range(0, total_stocks, batch_size):
            batch_symbols = target_symbols[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_stocks + batch_size - 1) // batch_size
            logger.info(
                "Backfill batch %s/%s (%s stocks)",
                batch_num,
                total_batches,
                len(batch_symbols),
            )

            cache_load_kwargs = {}
            if required_as_of_date is not None:
                cache_load_kwargs["required_as_of_date"] = required_as_of_date
            price_data_by_symbol, batch_cache_miss_symbols = calculator._load_price_data_for_batch(
                batch_symbols=batch_symbols,
                cache_only=policy.cache_only,
                **cache_load_kwargs,
            )
            price_coverage.record_batch(
                batch_symbols,
                batch_cache_miss_symbols,
            )

            for symbol in batch_symbols:
                symbol_dates = (
                    [
                        calculation_date
                        for calculation_date in ordered_dates
                        if symbol in explicit_eligible_symbol_sets[calculation_date]
                    ]
                    if explicit_eligible_symbol_sets is not None
                    else ordered_dates
                )
                try:
                    price_history = price_data_by_symbol.get(symbol)
                    if price_history is None or price_history.empty:
                        for calc_date in symbol_dates:
                            outcomes_by_date[calc_date].record_cache_miss()
                        continue

                    stock_metrics_by_date = calculator._calculate_stock_metrics_by_date_from_prices(
                        prices_df=price_history,
                        calculation_dates=symbol_dates,
                    )
                    for calc_date in symbol_dates:
                        daily_metrics = metrics_by_date[calc_date]
                        stock_metrics = stock_metrics_by_date.get(calc_date)
                        if stock_metrics is None:
                            outcomes_by_date[calc_date].record_insufficient()
                            continue
                        calculator._apply_stock_metrics(daily_metrics, stock_metrics)
                        outcomes_by_date[calc_date].record_scanned()
                except Exception as e:
                    logger.warning("Error processing %s in breadth backfill: %s", symbol, e)
                    for calc_date in symbol_dates:
                        outcomes_by_date[calc_date].record_error()

        prior_counts = calculator._get_prior_breadth_counts(ordered_dates[0], limit=10)
        existing_counts = calculator._get_existing_breadth_counts_by_date(
            ordered_dates[0],
            ordered_dates[-1],
        )
        rolling_counts = deque(prior_counts, maxlen=10)

        processed_dates: list[date] = []
        error_dates: list[str] = []

        shared_price_coverage = price_coverage.report()
        requested_dates = set(ordered_dates)
        timeline_dates = sorted(set(existing_counts.keys()) | requested_dates)
        for calc_date in timeline_dates:
            if calc_date in requested_dates:
                metrics = metrics_by_date[calc_date]
                metrics.update(
                    BreadthCoverageReport.from_parts(
                        shared_price_coverage,
                        outcomes_by_date[calc_date].report(),
                    ).to_daily_dict()
                )
                ratios = calculator._calculate_ratios_from_counts(list(rolling_counts))
                metrics['ratio_5day'] = ratios['ratio_5day']
                metrics['ratio_10day'] = ratios['ratio_10day']

                if metrics['total_stocks_scanned'] > 0:
                    processed_dates.append(calc_date)
                    rolling_counts.append({
                        'stocks_up_4pct': metrics['stocks_up_4pct'],
                        'stocks_down_4pct': metrics['stocks_down_4pct'],
                    })
                else:
                    error_dates.append(calc_date.strftime('%Y-%m-%d'))
                continue

            rolling_counts.append(existing_counts[calc_date])

        if processed_dates:
            total_duration_seconds = (datetime.now() - start_time).total_seconds()
            duration_per_day = round(total_duration_seconds / len(processed_dates), 2)
            for calc_date in processed_dates:
                metrics_by_date[calc_date]['calculation_duration_seconds'] = duration_per_day

            calculator._store_breadth_records(
                {
                    calc_date: metrics_by_date[calc_date]
                    for calc_date in processed_dates
                }
            )

        result = {
            'total_dates': len(ordered_dates),
            'processed': len(processed_dates),
            'errors': len(error_dates),
            'error_dates': error_dates,
        }
        if explicit_eligible_symbols is not None:
            result.update(
                {
                    "eligible_stocks_by_date": {
                        calculation_date.isoformat(): len(symbols)
                        for calculation_date, symbols in explicit_eligible_symbols.items()
                    },
                    "scanned_stocks_by_date": {
                        calculation_date.isoformat(): outcomes_by_date[
                            calculation_date
                        ].report().scanned
                        for calculation_date in ordered_dates
                    },
                    "calculation_errors_by_date": {
                        calculation_date.isoformat(): outcomes_by_date[
                            calculation_date
                        ].report().errors
                        for calculation_date in ordered_dates
                    },
                }
            )
        if exclude_unsupported_price_symbols:
            result.update({
                "skipped_unsupported_symbols": len(skipped_unsupported_symbols),
                "unsupported_symbols_sample": (
                    sorted(set(skipped_unsupported_symbols))[:20]
                ),
            })
        if policy.cache_only:
            aggregate_outcomes = sum(
                (
                    counter.report()
                    for counter in outcomes_by_date.values()
                ),
                start=BreadthOutcomeReport(),
            )
            overall_report = BreadthCoverageReport.from_parts(
                shared_price_coverage,
                aggregate_outcomes,
            )
            result.update(overall_report.to_backfill_dict())
        return BreadthBackfillResult(MappingProxyType(result))
