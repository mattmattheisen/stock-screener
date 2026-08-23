"""Typed evidence and assessment values for opportunity-state policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

POLICY_VERSION = "correction-survivors-v1"
SCHEMA_VERSION = 1


class ActionState(str, Enum):
    EXIT_RISK = "exit_risk"
    DETERIORATING = "deteriorating"
    EVENT_RISK = "event_risk"
    EXTENDED = "extended"
    DATA_LIMITED = "data_limited"
    SETUP_READY = "setup_ready"
    WATCH = "watch"


ACTION_STATES = tuple(ActionState)
OPPORTUNITY_PROJECTION_KEYS = (
    "correction_survivor",
    "resilience_score",
    "action_state",
    "opportunity_state",
)
OPPORTUNITY_EVIDENCE_KEYS = (
    "schema_version",
    "policy_version",
    "as_of_date",
    "market",
    "mic",
    "benchmark_symbol",
    "benchmark_as_of_date",
    "passed_checks",
    "failed_checks",
    "warnings",
    "score_pillars",
    "metrics",
    "data_availability",
    "action_reasons",
)
SCORE_PILLAR_KEYS = (
    "benchmark_leadership",
    "multi_horizon_rs",
    "trend_integrity",
    "structure_tightness",
    "liquidity_freshness",
)


@dataclass(frozen=True)
class InvalidationEvidence:
    code: str
    is_hard: bool


@dataclass(frozen=True)
class EventDateAvailability:
    value: date | None
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class ProvenanceEvidence:
    market: str | None
    mic: str | None
    as_of_date: date | None
    benchmark_symbol: str | None
    benchmark_as_of_date: date | None


@dataclass(frozen=True)
class LeadershipEvidence:
    benchmark_relative_return_65d: float | None
    rs_rating_1m: float | None
    rs_rating_3m: float | None
    rs_line_new_high: bool | None
    rs_line_blue_dot: bool | None


@dataclass(frozen=True)
class TrendEvidence:
    stage: int | None
    ma_alignment: bool | None
    invalidation_evidence_available: bool
    invalidation_flags: tuple[InvalidationEvidence, ...] | None


@dataclass(frozen=True)
class StructureEvidence:
    setup_payload_available: bool
    pattern_primary: str | None
    pattern_primary_available: bool
    squeeze: bool | None
    tight_closes_count: int | None
    quiet_days_count: int | None
    volume_vs_50d: float | None
    volume_dry_up_max: float | None


@dataclass(frozen=True)
class TradabilityEvidence:
    liquidity_available: bool
    liquidity_passes: bool | None
    feature_status: str | None
    is_scannable: bool | None


@dataclass(frozen=True)
class RiskEvidence:
    event_calendar_available: bool
    earnings_soon: bool | None
    setup_ready: bool | None
    in_early_zone: bool | None
    extended: bool | None


@dataclass(frozen=True)
class OpportunityEvidence:
    provenance: ProvenanceEvidence
    leadership: LeadershipEvidence
    trend: TrendEvidence
    structure: StructureEvidence
    tradability: TradabilityEvidence
    risk: RiskEvidence


@dataclass(frozen=True)
class OpportunityInputs:
    """Temporary flat compatibility input; new producers use OpportunityEvidence."""

    market: str | None
    mic: str | None
    as_of_date: date | None
    benchmark_symbol: str | None
    benchmark_as_of_date: date | None
    benchmark_relative_return_65d: float | None
    rs_rating_1m: float | None
    rs_rating_3m: float | None
    rs_line_new_high: bool | None
    rs_line_blue_dot: bool | None
    stage: int | None
    ma_alignment: bool | None
    invalidation_evidence_available: bool | None
    invalidation_flags: tuple[InvalidationEvidence, ...] | None
    setup_payload_available: bool | None
    pattern_primary: str | None
    pattern_primary_available: bool | None
    squeeze: bool | None
    tight_closes_count: int | None
    quiet_days_count: int | None
    volume_vs_50d: float | None
    volume_dry_up_max: float | None
    liquidity_available: bool | None
    liquidity_passes: bool | None
    feature_status: str | None
    is_scannable: bool | None
    event_calendar_available: bool | None
    earnings_soon: bool | None
    setup_ready: bool | None
    in_early_zone: bool | None
    extended: bool | None
    prior_run_required: bool
    prior_run_available: bool | None
    deterioration_confirmed: bool | None
    stewardship_status: str | None


@dataclass(frozen=True)
class OpportunityAssessment:
    correction_survivor: bool
    resilience_score: float | None
    score_pillars: dict[str, float | None]
    action_state: ActionState
    passed_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    warnings: tuple[str, ...]
    action_reasons: tuple[str, ...]
    metrics: dict[str, object]
    data_availability: dict[str, str]
    market: str | None
    mic: str | None
    as_of_date: date | None
    benchmark_symbol: str | None
    benchmark_as_of_date: date | None

    def projection(self) -> dict[str, object]:
        """Compatibility shim for callers migrating to the projection codec."""
        from .projection import serialize_opportunity_projection

        return serialize_opportunity_projection(self)


OpportunityStateResult = OpportunityAssessment
