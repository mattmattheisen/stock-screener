"""Versioned HTTP contract for persisted opportunity-state evidence."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ActionStateValue = Literal[
    "exit_risk",
    "deteriorating",
    "event_risk",
    "extended",
    "data_limited",
    "setup_ready",
    "watch",
]


class ScorePillarsResponse(BaseModel):
    """Exact five-pillar score decomposition for schema version 1."""

    model_config = ConfigDict(extra="forbid")

    benchmark_leadership: float | None
    multi_horizon_rs: float | None
    trend_integrity: float | None
    structure_tightness: float | None
    liquidity_freshness: float | None


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
    "OpportunityStateResponse",
    "ScorePillarsResponse",
    "validate_opportunity_projection",
]
