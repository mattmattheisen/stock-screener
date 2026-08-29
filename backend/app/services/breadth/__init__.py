"""Canonical market-breadth calculation primitives."""

from .contributors import (
    BREADTH_CONTRIBUTOR_SIGNALS,
    CONTRIBUTOR_RETENTION_SESSIONS,
    CONTRIBUTOR_SCHEMA_ID,
)
from .market_policy import BREADTH_MARKET_POLICIES, get_breadth_market_policy
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
    BreadthRatios,
    BreadthUniverseMember,
    BreadthUniverseSnapshot,
    SymbolBreadthEvaluation,
    SymbolBreadthSignals,
    SymbolMetricEligibility,
)

__all__ = [
    "BREADTH_MARKET_POLICIES",
    "BREADTH_CONTRIBUTOR_SIGNALS",
    "CONTRIBUTOR_RETENTION_SESSIONS",
    "CONTRIBUTOR_SCHEMA_ID",
    "CURRENT_BREADTH_CALCULATION_REVISION",
    "BreadthContributor",
    "BreadthContributorMetadata",
    "BreadthContributorSnapshotResult",
    "BreadthDailyCount",
    "BreadthDailyResult",
    "BreadthEngineBatchResult",
    "BreadthEligibilityCounts",
    "BreadthFormulaPolicy",
    "BreadthIndicatorValues",
    "BreadthMarketPolicy",
    "BreadthRatios",
    "BreadthUniverseMember",
    "BreadthUniverseSnapshot",
    "SymbolBreadthEvaluation",
    "SymbolBreadthSignals",
    "SymbolMetricEligibility",
    "get_breadth_market_policy",
]
