"""Versioned HTTP contract for persisted opportunity-state evidence."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

ActionStateValue = Literal[
    "exit_risk",
    "deteriorating",
    "event_risk",
    "extended",
    "data_limited",
    "setup_ready",
    "watch",
]

OPPORTUNITY_PROJECTION_KEYS = (
    "correction_survivor",
    "resilience_score",
    "action_state",
    "opportunity_state",
)
_SCORE_PILLAR_KEYS = (
    "benchmark_leadership",
    "multi_horizon_rs",
    "trend_integrity",
    "structure_tightness",
    "liquidity_freshness",
)


def _validate_optional_json_number(value: object, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number or null")


def validate_opportunity_projection_input(data: Any) -> Any:
    """Reject partial or coercive raw projections before schema defaults run."""
    if not isinstance(data, Mapping):
        return data

    present_keys = tuple(key for key in OPPORTUNITY_PROJECTION_KEYS if key in data)
    if not present_keys:
        return data
    if len(present_keys) != len(OPPORTUNITY_PROJECTION_KEYS):
        raise ValueError("opportunity projection must be all null or all present")
    if all(data[key] is None for key in OPPORTUNITY_PROJECTION_KEYS):
        return data
    if (
        data["correction_survivor"] is None
        or data["action_state"] is None
        or data["opportunity_state"] is None
    ):
        raise ValueError("opportunity projection must be all null or all present")

    if type(data["correction_survivor"]) is not bool:
        raise ValueError("correction_survivor must be a bool")
    _validate_optional_json_number(data["resilience_score"], "resilience_score")
    return data


class ScorePillarsResponse(BaseModel):
    """Exact five-pillar score decomposition for schema version 1."""

    model_config = ConfigDict(extra="forbid")

    benchmark_leadership: float | None
    multi_horizon_rs: float | None
    trend_integrity: float | None
    structure_tightness: float | None
    liquidity_freshness: float | None

    @model_validator(mode="before")
    @classmethod
    def _validate_raw_numbers(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            for key in _SCORE_PILLAR_KEYS:
                if key in data:
                    _validate_optional_json_number(data[key], f"score_pillars.{key}")
        return data


class OpportunityStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    policy_version: Literal["correction-survivors-v1"]
    as_of_date: str | None
    market: str | None
    mic: str | None
    benchmark_symbol: str | None
    benchmark_as_of_date: str | None
    passed_checks: list[str]
    failed_checks: list[str]
    warnings: list[str]
    score_pillars: ScorePillarsResponse
    metrics: dict[str, Any]
    data_availability: dict[str, str]
    action_reasons: list[str]


def validate_opportunity_projection(
    *,
    correction_survivor: bool | None,
    resilience_score: float | None,
    action_state: ActionStateValue | None,
    opportunity_state: OpportunityStateResponse | None,
) -> None:
    """Enforce legacy-null and computed-row coherence across the compact projection."""
    if (
        correction_survivor is None
        and resilience_score is None
        and action_state is None
        and opportunity_state is None
    ):
        return
    if correction_survivor is None or action_state is None or opportunity_state is None:
        raise ValueError("opportunity projection must be all null or all present")

    pillars = tuple(opportunity_state.score_pillars.model_dump().values())
    if resilience_score is None:
        if any(pillar is not None for pillar in pillars):
            raise ValueError("score pillars must be all null when resilience_score is null")
    else:
        if any(pillar is None for pillar in pillars):
            raise ValueError("score pillars must all be present when resilience_score is present")
        pillar_sum = round(sum(pillar for pillar in pillars if pillar is not None), 1)
        if pillar_sum != round(resilience_score, 1):
            raise ValueError("resilience_score must equal the score pillar sum")

    if action_state == "setup_ready" and correction_survivor is not True:
        raise ValueError("setup_ready requires correction_survivor=true")


__all__ = [
    "ActionStateValue",
    "OPPORTUNITY_PROJECTION_KEYS",
    "OpportunityStateResponse",
    "ScorePillarsResponse",
    "validate_opportunity_projection",
    "validate_opportunity_projection_input",
]
