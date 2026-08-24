"""Versioned HTTP contract for persisted opportunity-state evidence."""

import math
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.scanning.opportunity_state.model import (
    OPPORTUNITY_PROJECTION_KEYS,
    SCORE_PILLAR_KEYS,
    ActionState,
)
from app.domain.scanning.opportunity_state.projection import (
    validate_projection_coherence,
)

ActionStateValue = ActionState


def _validate_optional_json_number(value: object, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number or null")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


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
            for key in SCORE_PILLAR_KEYS:
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

    validate_projection_coherence(
        correction_survivor=correction_survivor,
        resilience_score=resilience_score,
        score_pillars=opportunity_state.score_pillars.model_dump(),
        action_state=ActionState(action_state),
    )


__all__ = [
    "ActionStateValue",
    "OPPORTUNITY_PROJECTION_KEYS",
    "SCORE_PILLAR_KEYS",
    "OpportunityStateResponse",
    "ScorePillarsResponse",
    "validate_opportunity_projection",
    "validate_opportunity_projection_input",
]
