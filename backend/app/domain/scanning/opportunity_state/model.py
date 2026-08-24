"""Typed evidence and assessment values for opportunity-state policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Generic, TypeVar

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

T = TypeVar("T")


@dataclass(frozen=True)
class EvidenceValue(Generic[T]):
    value: T | None
    available: bool


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
    invalidation: EvidenceValue[tuple[InvalidationEvidence, ...]]


@dataclass(frozen=True)
class StructureEvidence:
    setup_payload_available: bool
    primary_pattern: EvidenceValue[str]
    squeeze: bool | None
    tight_closes_count: int | None
    quiet_days_count: int | None
    volume_vs_50d: float | None
    volume_dry_up_max: float | None


@dataclass(frozen=True)
class TradabilityEvidence:
    liquidity: EvidenceValue[bool]
    feature_status: str | None
    is_scannable: bool | None


@dataclass(frozen=True)
class RiskEvidence:
    event_risk: EvidenceValue[bool]
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
class OpportunityAssessment:
    correction_survivor: bool
    resilience_score: float | None
    score_pillars: Mapping[str, float | None]
    action_state: ActionState
    passed_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    warnings: tuple[str, ...]
    action_reasons: tuple[str, ...]
    metrics: Mapping[str, object]
    data_availability: Mapping[str, str]
    market: str | None
    mic: str | None
    as_of_date: date | None
    benchmark_symbol: str | None
    benchmark_as_of_date: date | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "score_pillars", MappingProxyType(dict(self.score_pillars)))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(
            self,
            "data_availability",
            MappingProxyType(dict(self.data_availability)),
        )

    def with_metrics(self, metrics: Mapping[str, object]) -> OpportunityAssessment:
        return replace(self, metrics={**self.metrics, **metrics})

    def with_action_reasons(self, reasons: tuple[str, ...]) -> OpportunityAssessment:
        return replace(self, action_reasons=tuple(reasons))

OpportunityStateResult = OpportunityAssessment
