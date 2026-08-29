"""Canonical range engine for all market-breadth calculation paths."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from types import MappingProxyType

import pandas as pd

from app.services.point_in_time_universe_service import (
    hash_point_in_time_universe_symbols,
)

from .contributors import (
    CONTRIBUTOR_SCHEMA_ID,
    NO_GROUP_LABEL,
    reconcile_contributor_counts,
)
from .formulas import evaluate_symbol_at, prepare_feature_frame, validate_price_frame
from .ratios import calculate_inclusive_ratios
from .types import (
    CURRENT_BREADTH_CALCULATION_REVISION,
    BreadthContributor,
    BreadthContributorMetadata,
    BreadthContributorSnapshotResult,
    BreadthDailyCount,
    BreadthDailyResult,
    BreadthEngineBatchResult,
    BreadthEligibilityCounts,
    BreadthFormulaPolicy,
    BreadthIndicatorValues,
    BreadthMarketPolicy,
    BreadthUniverseSnapshot,
    SymbolBreadthEvaluation,
    SymbolBreadthSignals,
)
from .universe import breadth_eligibility_signature

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BreadthEngineRequest:
    market: str
    dates: tuple[date, ...]
    universes_by_date: Mapping[date, BreadthUniverseSnapshot]
    prices_by_symbol: Mapping[str, pd.DataFrame]
    market_policy: BreadthMarketPolicy
    seed_counts: tuple[BreadthDailyCount, ...] = ()
    contributor_metadata_by_date: Mapping[
        date, Mapping[str, BreadthContributorMetadata]
    ] = field(default_factory=dict)
    policy: BreadthFormulaPolicy = field(default_factory=BreadthFormulaPolicy)


class BreadthEngine:
    def calculate(
        self, request: BreadthEngineRequest
    ) -> Mapping[date, BreadthDailyResult]:
        """Compatibility projection for aggregate-only callers."""
        return self.calculate_with_contributors(request).daily_results

    def calculate_with_contributors(
        self, request: BreadthEngineRequest
    ) -> BreadthEngineBatchResult:
        market = request.market.strip().upper()
        if request.market_policy.market != market:
            raise ValueError(
                f"Breadth policy market {request.market_policy.market} "
                f"does not match request market {market}"
            )

        dates = tuple(request.dates)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("Breadth calculation dates must be ordered and unique")

        currencies_by_symbol: dict[str, str] = {}
        for calculation_date in dates:
            snapshot = request.universes_by_date.get(calculation_date)
            if snapshot is None:
                raise ValueError(
                    f"Missing breadth universe for {calculation_date.isoformat()}"
                )
            if snapshot.calculation_date != calculation_date:
                raise ValueError("Breadth universe date does not match request date")
            for member in snapshot.members:
                prior_currency = currencies_by_symbol.setdefault(
                    member.symbol,
                    member.currency.upper(),
                )
                if prior_currency != member.currency.upper():
                    raise ValueError(
                        f"Currency changed within breadth range for {member.symbol}"
                    )

        features_by_symbol: dict[str, pd.DataFrame] = {}
        for symbol in currencies_by_symbol:
            prices = request.prices_by_symbol.get(symbol)
            if prices is None or prices.empty:
                continue
            try:
                validate_price_frame(prices)
            except ValueError as exc:
                logger.warning(
                    "Skipping malformed breadth prices for %s: %s", symbol, exc
                )
                continue
            features_by_symbol[symbol] = prepare_feature_frame(
                prices,
                atr_period=request.policy.atr_period,
            )

        partial_results: dict[date, BreadthDailyResult] = {}
        contributor_snapshots: dict[date, BreadthContributorSnapshotResult] = {}
        daily_counts: list[BreadthDailyCount] = []
        for calculation_date in dates:
            snapshot = request.universes_by_date[calculation_date]
            evaluations_by_symbol: dict[str, SymbolBreadthEvaluation] = {}
            for member in snapshot.members:
                features = features_by_symbol.get(member.symbol)
                if features is None or not member.is_common_stock:
                    continue
                evaluations_by_symbol[member.symbol] = evaluate_symbol_at(
                    features,
                    calculation_date,
                    request.policy,
                    request.market_policy,
                    stockbee_currency_matches=(
                        member.currency.upper() == request.market_policy.currency
                    ),
                )

            signals_by_symbol: dict[str, SymbolBreadthSignals] = {
                symbol: evaluation.signals
                for symbol, evaluation in evaluations_by_symbol.items()
            }
            signals = tuple(signals_by_symbol.values())
            eligibility = BreadthEligibilityCounts(
                advance_decline_eligible_count=sum(
                    item.eligibility.advance_decline for item in signals
                ),
                stockbee_daily_eligible_count=sum(
                    item.eligibility.stockbee_daily for item in signals
                ),
                stockbee_month_eligible_count=sum(
                    item.eligibility.stockbee_month for item in signals
                ),
                stockbee_34day_eligible_count=sum(
                    item.eligibility.stockbee_34day for item in signals
                ),
                stockbee_quarter_eligible_count=sum(
                    item.eligibility.stockbee_quarter for item in signals
                ),
                t2108_eligible_count=sum(item.eligibility.t2108 for item in signals),
                high_low_52week_eligible_count=sum(
                    item.eligibility.high_low_52week for item in signals
                ),
                atr_extension_eligible_count=sum(
                    item.eligibility.atr_extension for item in signals
                ),
            )
            t2108_count = sum(item.t2108_above for item in signals)
            values = BreadthIndicatorValues(
                stocks_up_4pct=sum(item.up_4pct for item in signals),
                stocks_down_4pct=sum(item.down_4pct for item in signals),
                stocks_up_25pct_quarter=sum(item.up_25pct_quarter for item in signals),
                stocks_down_25pct_quarter=sum(
                    item.down_25pct_quarter for item in signals
                ),
                stocks_up_25pct_month=sum(item.up_25pct_month for item in signals),
                stocks_down_25pct_month=sum(item.down_25pct_month for item in signals),
                stocks_up_50pct_month=sum(item.up_50pct_month for item in signals),
                stocks_down_50pct_month=sum(item.down_50pct_month for item in signals),
                stocks_up_13pct_34days=sum(item.up_13pct_34days for item in signals),
                stocks_down_13pct_34days=sum(
                    item.down_13pct_34days for item in signals
                ),
                advancing_count=sum(item.advancing for item in signals),
                declining_count=sum(item.declining for item in signals),
                unchanged_count=sum(item.unchanged for item in signals),
                new_high_52week_count=sum(item.new_high_52week for item in signals),
                new_low_52week_count=sum(item.new_low_52week for item in signals),
                t2108_count=t2108_count,
                t2108_pct=(
                    round(t2108_count / eligibility.t2108_eligible_count * 100.0, 2)
                    if eligibility.t2108_eligible_count
                    else None
                ),
                atr_10x_extension_count=sum(item.atr_10x_extension for item in signals),
            )

            if (
                values.advancing_count + values.declining_count + values.unchanged_count
                != eligibility.advance_decline_eligible_count
            ):
                raise AssertionError("Advance/decline counts do not reconcile")
            if not 0 <= values.t2108_count <= eligibility.t2108_eligible_count:
                raise AssertionError("T2108 count exceeds its eligible denominator")
            if (
                request.policy.calculation_revision
                != CURRENT_BREADTH_CALCULATION_REVISION
            ):
                raise AssertionError(
                    "Canonical breadth engine must produce the current revision"
                )

            stockbee_symbols = tuple(
                sorted(
                    symbol
                    for symbol, item in signals_by_symbol.items()
                    if item.eligibility.stockbee_liquidity
                )
            )
            result = BreadthDailyResult(
                market=market,
                calculation_date=calculation_date,
                values=values,
                eligibility=eligibility,
                broad_universe_count=len(snapshot.members),
                eligibility_signature=breadth_eligibility_signature(
                    member.symbol for member in snapshot.members
                ),
                stockbee_eligibility_signature=hash_point_in_time_universe_symbols(
                    stockbee_symbols
                ),
                calculation_revision=request.policy.calculation_revision,
            )
            partial_results[calculation_date] = result
            metadata_by_symbol = request.contributor_metadata_by_date.get(
                calculation_date,
                {},
            )
            contributors: list[BreadthContributor] = []
            for symbol in sorted(evaluations_by_symbol):
                evaluation = evaluations_by_symbol[symbol]
                if not evaluation.qualifying_values:
                    continue
                metadata = metadata_by_symbol.get(
                    symbol,
                    BreadthContributorMetadata(),
                )
                company_name = (
                    str(metadata.company_name).strip()
                    if metadata.company_name is not None
                    and str(metadata.company_name).strip()
                    else None
                )
                group = str(metadata.ibd_industry_group or "").strip() or NO_GROUP_LABEL
                contributors.append(
                    BreadthContributor(
                        symbol=symbol,
                        company_name=company_name,
                        ibd_industry_group=group,
                        daily_change_pct=evaluation.daily_change_pct,
                        signals=MappingProxyType(dict(evaluation.qualifying_values)),
                    )
                )
            contributor_snapshot = BreadthContributorSnapshotResult(
                market=market,
                calculation_date=calculation_date,
                calculation_revision=request.policy.calculation_revision,
                schema_id=CONTRIBUTOR_SCHEMA_ID,
                contributors=tuple(contributors),
            )
            reconcile_contributor_counts(contributor_snapshot, result)
            contributor_snapshots[calculation_date] = contributor_snapshot
            daily_counts.append(
                BreadthDailyCount(
                    date=calculation_date,
                    stocks_up_4pct=values.stocks_up_4pct,
                    stocks_down_4pct=values.stocks_down_4pct,
                    market=result.market,
                    calculation_revision=result.calculation_revision,
                )
            )

        ratios_by_date = calculate_inclusive_ratios(
            daily_counts,
            request.seed_counts,
            market=market,
            calculation_revision=request.policy.calculation_revision,
        )
        daily_results = {
            calculation_date: replace(
                result,
                values=replace(
                    result.values,
                    ratio_5day=ratios_by_date[calculation_date].ratio_5day,
                    ratio_10day=ratios_by_date[calculation_date].ratio_10day,
                ),
            )
            for calculation_date, result in partial_results.items()
        }
        return BreadthEngineBatchResult(
            daily_results=MappingProxyType(daily_results),
            contributor_snapshots=MappingProxyType(contributor_snapshots),
        )
