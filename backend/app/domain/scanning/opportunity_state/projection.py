"""Versioned opportunity projection serialization boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from .model import (
    OPPORTUNITY_EVIDENCE_KEYS,
    OPPORTUNITY_PROJECTION_KEYS,
    POLICY_VERSION,
    SCHEMA_VERSION,
    SCORE_PILLAR_KEYS,
    ActionState,
    OpportunityAssessment,
)


def serialize_opportunity_projection(
    result: OpportunityAssessment,
) -> dict[str, object]:
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "as_of_date": result.as_of_date.isoformat() if result.as_of_date else None,
        "market": result.market,
        "mic": result.mic,
        "benchmark_symbol": result.benchmark_symbol,
        "benchmark_as_of_date": (
            result.benchmark_as_of_date.isoformat()
            if result.benchmark_as_of_date
            else None
        ),
        "passed_checks": list(result.passed_checks),
        "failed_checks": list(result.failed_checks),
        "warnings": list(result.warnings),
        "score_pillars": dict(result.score_pillars),
        "metrics": dict(result.metrics),
        "data_availability": dict(result.data_availability),
        "action_reasons": list(result.action_reasons),
    }
    return {
        "correction_survivor": result.correction_survivor,
        "resilience_score": result.resilience_score,
        "action_state": result.action_state.value,
        "opportunity_state": evidence,
    }


def parse_opportunity_projection(
    projection: Mapping[str, object] | None,
) -> OpportunityAssessment | None:
    """Restore a strict typed result while preserving absent legacy rows."""
    if projection is None:
        return None
    if not isinstance(projection, Mapping):
        raise TypeError("projection must be a mapping")
    present_keys = tuple(key for key in OPPORTUNITY_PROJECTION_KEYS if key in projection)
    if not present_keys:
        return None
    if len(present_keys) != len(OPPORTUNITY_PROJECTION_KEYS):
        raise ValueError("opportunity projection must be all null or all present")
    _require_exact_keys(projection, OPPORTUNITY_PROJECTION_KEYS, "projection")
    if all(projection[key] is None for key in OPPORTUNITY_PROJECTION_KEYS):
        return None
    if projection["opportunity_state"] is None:
        raise ValueError("opportunity projection must be all null or all present")

    evidence = _mapping(projection["opportunity_state"], "opportunity_state")
    _require_exact_keys(evidence, OPPORTUNITY_EVIDENCE_KEYS, "opportunity_state")
    if evidence.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("opportunity_state.schema_version is unsupported or malformed")
    if evidence.get("policy_version") != POLICY_VERSION:
        raise ValueError("opportunity_state.policy_version is unsupported or malformed")

    action_state = _action_state(projection.get("action_state"))
    correction_survivor = projection.get("correction_survivor")
    if type(correction_survivor) is not bool:
        raise ValueError("correction_survivor must be a bool")
    resilience_score = _optional_number(projection.get("resilience_score"), "resilience_score")
    score_pillars = _score_pillar_mapping(evidence.get("score_pillars"))
    validate_projection_coherence(
        correction_survivor=correction_survivor,
        resilience_score=resilience_score,
        score_pillars=score_pillars,
        action_state=action_state,
    )

    return OpportunityAssessment(
        correction_survivor=correction_survivor,
        resilience_score=resilience_score,
        score_pillars=score_pillars,
        action_state=action_state,
        passed_checks=_string_tuple(evidence.get("passed_checks"), "passed_checks"),
        failed_checks=_string_tuple(evidence.get("failed_checks"), "failed_checks"),
        warnings=_string_tuple(evidence.get("warnings"), "warnings"),
        action_reasons=_string_tuple(evidence.get("action_reasons"), "action_reasons"),
        metrics=dict(_mapping(evidence.get("metrics"), "metrics")),
        data_availability=_string_mapping(evidence.get("data_availability"), "data_availability"),
        market=_optional_string(evidence.get("market"), "market"),
        mic=_optional_string(evidence.get("mic"), "mic"),
        as_of_date=_optional_date(evidence.get("as_of_date"), "as_of_date"),
        benchmark_symbol=_optional_string(evidence.get("benchmark_symbol"), "benchmark_symbol"),
        benchmark_as_of_date=_optional_date(
            evidence.get("benchmark_as_of_date"), "benchmark_as_of_date"
        ),
    )


opportunity_result_from_projection = parse_opportunity_projection


def validate_projection_coherence(
    *,
    correction_survivor: bool,
    resilience_score: float | None,
    score_pillars: Mapping[str, float | None],
    action_state: ActionState,
) -> None:
    pillars = tuple(score_pillars.values())
    if resilience_score is None:
        if any(pillar is not None for pillar in pillars):
            raise ValueError("score pillars must be all null when resilience_score is null")
    else:
        if any(pillar is None for pillar in pillars):
            raise ValueError("score pillars must all be present when resilience_score is present")
        pillar_sum = round(sum(pillar for pillar in pillars if pillar is not None), 1)
        if pillar_sum != round(resilience_score, 1):
            raise ValueError("resilience_score must equal the score pillar sum")
    if action_state is ActionState.SETUP_READY and not correction_survivor:
        raise ValueError("setup_ready requires correction_survivor=true")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    return value


def _require_exact_keys(
    mapping: Mapping[str, object], required: tuple[str, ...], name: str
) -> None:
    missing = tuple(key for key in required if key not in mapping)
    if missing:
        raise ValueError(f"{name} is missing required keys: {', '.join(missing)}")
    unexpected = tuple(key for key in mapping if key not in required)
    if unexpected:
        raise ValueError(f"{name} has unexpected keys: {', '.join(unexpected)}")


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return tuple(value)


def _string_mapping(value: object, name: str) -> dict[str, str]:
    mapping = _mapping(value, name)
    if not all(isinstance(item, str) for item in mapping.values()):
        raise ValueError(f"{name} values must be strings")
    return dict(mapping)


def _score_pillar_mapping(value: object) -> dict[str, float | None]:
    mapping = _mapping(value, "score_pillars")
    _require_exact_keys(mapping, SCORE_PILLAR_KEYS, "score_pillars")
    return {
        key: _optional_number(mapping[key], f"score_pillars.{key}")
        for key in SCORE_PILLAR_KEYS
    }


def _optional_string(value: object, name: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{name} must be a string or null")


def _optional_date(value: object, name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO date string or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date string or null") from exc


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number or null")
    return float(value)


def _action_state(value: object) -> ActionState:
    if not isinstance(value, str):
        raise TypeError("action_state must be a valid action-state string")
    try:
        return ActionState(value)
    except ValueError as exc:
        raise ValueError("action_state must be a valid action-state string") from exc
