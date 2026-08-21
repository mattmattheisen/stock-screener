"""Pure policy for classifying correction survivors and their action state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
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


_STATE_PRECEDENCE = tuple(ActionState)
_STATE_PRIORITY = {state: index for index, state in enumerate(_STATE_PRECEDENCE)}
_PROJECTION_KEYS = (
    "correction_survivor",
    "resilience_score",
    "action_state",
    "opportunity_state",
)
_EVIDENCE_KEYS = (
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
_SCORE_PILLAR_KEYS = (
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
class OpportunityInputs:
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
class OpportunityStateResult:
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
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "market": self.market,
            "mic": self.mic,
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_as_of_date": (
                self.benchmark_as_of_date.isoformat() if self.benchmark_as_of_date else None
            ),
            "passed_checks": list(self.passed_checks),
            "failed_checks": list(self.failed_checks),
            "warnings": list(self.warnings),
            "score_pillars": dict(self.score_pillars),
            "metrics": dict(self.metrics),
            "data_availability": dict(self.data_availability),
            "action_reasons": list(self.action_reasons),
        }
        return {
            "correction_survivor": self.correction_survivor,
            "resilience_score": self.resilience_score,
            "action_state": self.action_state.value,
            "opportunity_state": evidence,
        }


def normalize_event_date(raw: object, *, key_present: bool) -> EventDateAvailability:
    if not key_present:
        return EventDateAvailability(None, False, "missing_event_calendar")
    if raw is None:
        return EventDateAvailability(None, True)
    if isinstance(raw, datetime):
        return EventDateAvailability(raw.date(), True)
    if isinstance(raw, date):
        return EventDateAvailability(raw, True)
    if isinstance(raw, str):
        try:
            return EventDateAvailability(date.fromisoformat(raw[:10]), True)
        except ValueError:
            return EventDateAvailability(None, False, "invalid_next_earnings_date")
    return EventDateAvailability(None, False, "invalid_next_earnings_date")


def evaluate_opportunity_state(inputs: OpportunityInputs) -> OpportunityStateResult:
    """Evaluate one snapshot without consulting external state or market posture."""
    hard_invalidation = _hard_invalidation(
        inputs.invalidation_flags, inputs.invalidation_evidence_available
    )
    benchmark_is_future = _benchmark_is_future(inputs)
    required_complete = _required_evidence_complete(inputs, benchmark_is_future)
    score_pillars = _score_pillars(inputs, benchmark_is_future)
    score = _resilience_score(score_pillars)

    leadership_gate = _leadership_gate(inputs)
    trend_gate = _trend_gate(inputs, hard_invalidation)
    structure_gate = _structure_gate(inputs)
    liquidity_gate = inputs.liquidity_available is True and inputs.liquidity_passes is True
    freshness_gate = inputs.feature_status == "complete" and inputs.is_scannable is True
    correction_survivor = (
        required_complete
        and leadership_gate
        and trend_gate
        and structure_gate
        and liquidity_gate
        and freshness_gate
    )

    passed_checks: list[str] = []
    failed_checks: list[str] = []
    _record_check(passed_checks, failed_checks, "required_evidence", required_complete)
    _record_check(passed_checks, failed_checks, "leadership_gate", leadership_gate)
    _record_check(passed_checks, failed_checks, "trend_gate", trend_gate)
    _record_check(passed_checks, failed_checks, "structure_gate", structure_gate)
    _record_check(passed_checks, failed_checks, "liquidity_gate", liquidity_gate)
    _record_check(passed_checks, failed_checks, "freshness_gate", freshness_gate)
    if benchmark_is_future:
        failed_checks.append("future_benchmark_date")

    warnings: list[str] = []
    if _benchmark_is_lagged(inputs):
        warnings.append("benchmark_date_lag")

    action_state, action_reasons = _resolve_action_state(
        inputs, hard_invalidation, required_complete, benchmark_is_future
    )
    return OpportunityStateResult(
        correction_survivor=correction_survivor,
        resilience_score=score,
        score_pillars=score_pillars,
        action_state=action_state,
        passed_checks=tuple(passed_checks),
        failed_checks=tuple(failed_checks),
        warnings=tuple(warnings),
        action_reasons=action_reasons,
        metrics=_metrics(inputs, hard_invalidation),
        data_availability=_data_availability(inputs, required_complete, benchmark_is_future),
        market=inputs.market,
        mic=inputs.mic,
        as_of_date=inputs.as_of_date,
        benchmark_symbol=inputs.benchmark_symbol,
        benchmark_as_of_date=inputs.benchmark_as_of_date,
    )


def opportunity_result_from_projection(
    projection: Mapping[str, object] | None,
) -> OpportunityStateResult | None:
    """Restore a typed result, preserving compatibility with rows lacking the legacy payload."""
    if projection is None:
        return None
    if not isinstance(projection, Mapping):
        raise TypeError("projection must be a mapping")
    if "opportunity_state" not in projection:
        return None
    _require_keys(projection, _PROJECTION_KEYS, "projection")

    evidence = _mapping(projection["opportunity_state"], "opportunity_state")
    _require_keys(evidence, _EVIDENCE_KEYS, "opportunity_state")
    if evidence.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("opportunity_state.schema_version is unsupported or malformed")
    if evidence.get("policy_version") != POLICY_VERSION:
        raise ValueError("opportunity_state.policy_version is unsupported or malformed")

    action_state = _action_state(projection.get("action_state"))
    correction_survivor = projection.get("correction_survivor")
    if type(correction_survivor) is not bool:
        raise ValueError("correction_survivor must be a bool")
    resilience_score = _optional_number(projection.get("resilience_score"), "resilience_score")

    return OpportunityStateResult(
        correction_survivor=correction_survivor,
        resilience_score=resilience_score,
        score_pillars=_score_pillar_mapping(evidence.get("score_pillars")),
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


def overlay_stewardship_state(
    result: OpportunityStateResult,
    stewardship_status: str | None,
    prior_run_available: bool,
) -> OpportunityStateResult:
    """Apply a requested cross-run state only when it outranks the persisted state."""
    if prior_run_available is not True or stewardship_status is None:
        return result
    try:
        stewardship_state = ActionState(stewardship_status)
    except ValueError:
        return result
    if _STATE_PRIORITY[stewardship_state] >= _STATE_PRIORITY[result.action_state]:
        return result

    reason = f"stewardship_{stewardship_state.value}"
    action_reasons = result.action_reasons
    if reason not in action_reasons:
        action_reasons += (reason,)
    return replace(result, action_state=stewardship_state, action_reasons=action_reasons)


def _required_evidence_complete(inputs: OpportunityInputs, benchmark_is_future: bool) -> bool:
    required_values = (
        inputs.as_of_date,
        inputs.benchmark_symbol,
        inputs.benchmark_as_of_date,
        inputs.benchmark_relative_return_65d,
        inputs.rs_rating_1m,
        inputs.rs_rating_3m,
        inputs.rs_line_new_high,
        inputs.rs_line_blue_dot,
        inputs.stage,
        inputs.ma_alignment,
        inputs.invalidation_flags,
        inputs.pattern_primary,
        inputs.squeeze,
        inputs.tight_closes_count,
        inputs.quiet_days_count,
        inputs.volume_vs_50d,
        inputs.volume_dry_up_max,
        inputs.liquidity_passes,
        inputs.feature_status,
        inputs.is_scannable,
        inputs.earnings_soon,
        inputs.setup_ready,
        inputs.in_early_zone,
        inputs.extended,
        inputs.deterioration_confirmed,
    )
    availability_flags = (
        inputs.invalidation_evidence_available,
        inputs.setup_payload_available,
        inputs.liquidity_available,
        inputs.event_calendar_available,
    )
    return (
        not benchmark_is_future
        and all(value is not None for value in required_values)
        and all(value is True for value in availability_flags)
        and (not inputs.prior_run_required or inputs.prior_run_available is True)
        and _valid_invalidation_flags(inputs.invalidation_flags)
    )


def _score_pillars(
    inputs: OpportunityInputs, benchmark_is_future: bool
) -> dict[str, float | None]:
    if benchmark_is_future or not _score_inputs_known(inputs):
        return {key: None for key in _SCORE_PILLAR_KEYS}

    hard_invalidation = _hard_invalidation(
        inputs.invalidation_flags, inputs.invalidation_evidence_available
    )
    leadership = float(
        (12 if inputs.benchmark_relative_return_65d > 0 else 0)
        + (8 if inputs.rs_line_new_high or inputs.rs_line_blue_dot else 0)
    )
    multi_horizon = (
        10 * _clamp(inputs.rs_rating_1m) / 100
        + 10 * _clamp(inputs.rs_rating_3m) / 100
    )
    trend = float(
        8 * (inputs.stage in (1, 2))
        + 8 * bool(inputs.ma_alignment)
        + 4 * (not hard_invalidation)
    )
    structure = float(
        8 * bool(inputs.pattern_primary)
        + 4 * bool(inputs.squeeze)
        + 3 * (inputs.tight_closes_count >= 3)
        + 3 * (inputs.quiet_days_count >= 3)
        + 2 * (inputs.volume_vs_50d <= inputs.volume_dry_up_max)
    )
    tradability = float(
        10 * bool(inputs.liquidity_passes)
        + 10 * (inputs.feature_status == "complete" and inputs.is_scannable is True)
    )
    return {
        "benchmark_leadership": leadership,
        "multi_horizon_rs": multi_horizon,
        "trend_integrity": trend,
        "structure_tightness": structure,
        "liquidity_freshness": tradability,
    }


def _resilience_score(score_pillars: Mapping[str, float | None]) -> float | None:
    values = tuple(score_pillars[key] for key in _SCORE_PILLAR_KEYS)
    if any(value is None for value in values):
        return None
    return round(sum(values), 1)


def _score_inputs_known(inputs: OpportunityInputs) -> bool:
    values = (
        inputs.benchmark_relative_return_65d,
        inputs.rs_rating_1m,
        inputs.rs_rating_3m,
        inputs.rs_line_new_high,
        inputs.rs_line_blue_dot,
        inputs.stage,
        inputs.ma_alignment,
        inputs.invalidation_flags,
        inputs.pattern_primary,
        inputs.squeeze,
        inputs.tight_closes_count,
        inputs.quiet_days_count,
        inputs.volume_vs_50d,
        inputs.volume_dry_up_max,
        inputs.liquidity_passes,
        inputs.feature_status,
        inputs.is_scannable,
    )
    return (
        all(value is not None for value in values)
        and inputs.invalidation_evidence_available is True
        and inputs.setup_payload_available is True
        and inputs.liquidity_available is True
        and _valid_invalidation_flags(inputs.invalidation_flags)
    )


def _leadership_gate(inputs: OpportunityInputs) -> bool:
    return (
        inputs.benchmark_relative_return_65d is not None
        and inputs.benchmark_relative_return_65d > 0
        and inputs.rs_rating_1m is not None
        and inputs.rs_rating_1m >= 70
        and inputs.rs_rating_3m is not None
        and inputs.rs_rating_3m >= 70
        and (inputs.rs_line_new_high is True or inputs.rs_line_blue_dot is True)
    )


def _trend_gate(inputs: OpportunityInputs, hard_invalidation: bool | None) -> bool:
    return inputs.stage in (1, 2) and inputs.ma_alignment is True and hard_invalidation is False


def _structure_gate(inputs: OpportunityInputs) -> bool:
    return (
        bool(inputs.pattern_primary)
        and inputs.squeeze is True
        and inputs.tight_closes_count is not None
        and inputs.tight_closes_count >= 3
        and inputs.quiet_days_count is not None
        and inputs.quiet_days_count >= 3
        and inputs.volume_vs_50d is not None
        and inputs.volume_dry_up_max is not None
        and inputs.volume_vs_50d <= inputs.volume_dry_up_max
    )


def _hard_invalidation(
    flags: tuple[InvalidationEvidence, ...] | None, evidence_available: bool | None
) -> bool | None:
    if _valid_invalidation_flags(flags) and any(flag.is_hard for flag in flags):
        return True
    if evidence_available is True and _valid_invalidation_flags(flags):
        return False
    return None


def _valid_invalidation_flags(flags: tuple[InvalidationEvidence, ...] | None) -> bool:
    return isinstance(flags, tuple) and all(isinstance(flag, InvalidationEvidence) for flag in flags)


def _benchmark_is_future(inputs: OpportunityInputs) -> bool:
    return (
        inputs.as_of_date is not None
        and inputs.benchmark_as_of_date is not None
        and inputs.benchmark_as_of_date > inputs.as_of_date
    )


def _benchmark_is_lagged(inputs: OpportunityInputs) -> bool:
    return (
        inputs.as_of_date is not None
        and inputs.benchmark_as_of_date is not None
        and inputs.benchmark_as_of_date < inputs.as_of_date
    )


def _resolve_action_state(
    inputs: OpportunityInputs,
    hard_invalidation: bool | None,
    required_complete: bool,
    benchmark_is_future: bool,
) -> tuple[ActionState, tuple[str, ...]]:
    if hard_invalidation is True:
        return ActionState.EXIT_RISK, _hard_invalidation_reasons(inputs.invalidation_flags)
    if inputs.deterioration_confirmed is True:
        return ActionState.DETERIORATING, ("deterioration_confirmed",)
    if inputs.earnings_soon is True:
        return ActionState.EVENT_RISK, ("earnings_soon",)
    if inputs.extended is True:
        return ActionState.EXTENDED, ("extended",)
    if not required_complete:
        reasons = ("future_benchmark_date",) if benchmark_is_future else ("required_evidence",)
        return ActionState.DATA_LIMITED, reasons
    if inputs.setup_ready is True and inputs.in_early_zone is True:
        return ActionState.SETUP_READY, ("setup_ready",)
    return ActionState.WATCH, ("watch",)


def _hard_invalidation_reasons(
    flags: tuple[InvalidationEvidence, ...] | None,
) -> tuple[str, ...]:
    if flags is None:
        return ("hard_invalidation",)
    return tuple(f"hard_invalidation:{flag.code}" for flag in flags if flag.is_hard)


def _metrics(inputs: OpportunityInputs, hard_invalidation: bool | None) -> dict[str, object]:
    return {
        "benchmark_relative_return_65d": inputs.benchmark_relative_return_65d,
        "rs_rating_1m": inputs.rs_rating_1m,
        "rs_rating_3m": inputs.rs_rating_3m,
        "rs_line_new_high": inputs.rs_line_new_high,
        "rs_line_blue_dot": inputs.rs_line_blue_dot,
        "stage": inputs.stage,
        "ma_alignment": inputs.ma_alignment,
        "hard_invalidation": hard_invalidation,
        "pattern_primary": inputs.pattern_primary,
        "squeeze": inputs.squeeze,
        "tight_closes_count": inputs.tight_closes_count,
        "quiet_days_count": inputs.quiet_days_count,
        "volume_vs_50d": inputs.volume_vs_50d,
        "volume_dry_up_max": inputs.volume_dry_up_max,
        "liquidity_passes": inputs.liquidity_passes,
        "feature_status": inputs.feature_status,
        "is_scannable": inputs.is_scannable,
    }


def _data_availability(
    inputs: OpportunityInputs, required_complete: bool, benchmark_is_future: bool
) -> dict[str, str]:
    return {
        "required_evidence": "complete" if required_complete else "incomplete",
        "benchmark": "future" if benchmark_is_future else _availability(inputs.benchmark_as_of_date),
        "invalidation": _availability_flag(inputs.invalidation_evidence_available),
        "setup": _availability_flag(inputs.setup_payload_available),
        "liquidity": _availability_flag(inputs.liquidity_available),
        "event_calendar": _availability_flag(inputs.event_calendar_available),
        "prior_run": (
            "not_requested"
            if not inputs.prior_run_required
            else _availability_flag(inputs.prior_run_available)
        ),
    }


def _availability(value: object) -> str:
    return "available" if value is not None else "unavailable"


def _availability_flag(value: bool | None) -> str:
    if value is True:
        return "available"
    if value is False:
        return "unavailable"
    return "unknown"


def _record_check(passed: list[str], failed: list[str], name: str, condition: bool) -> None:
    (passed if condition else failed).append(name)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    return value


def _require_keys(mapping: Mapping[str, object], required: tuple[str, ...], name: str) -> None:
    missing = tuple(key for key in required if key not in mapping)
    if missing:
        raise ValueError(f"{name} is missing required keys: {', '.join(missing)}")


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
    _require_keys(mapping, _SCORE_PILLAR_KEYS, "score_pillars")
    return {
        key: _optional_number(mapping[key], f"score_pillars.{key}")
        for key in _SCORE_PILLAR_KEYS
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
