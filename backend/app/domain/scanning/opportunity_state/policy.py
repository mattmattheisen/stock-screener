"""Pure policy for classifying correction survivors and their action state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from .model import (
    SCORE_PILLAR_KEYS,
    ActionState,
    EventDateAvailability,
    InvalidationEvidence,
    OpportunityEvidence,
    OpportunityStateResult,
)

_SCORE_PILLAR_KEYS = SCORE_PILLAR_KEYS


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


def evaluate_opportunity_state(inputs: OpportunityEvidence) -> OpportunityStateResult:
    """Evaluate one snapshot without consulting external state or market posture."""
    hard_invalidation = _hard_invalidation(
        inputs.trend.invalidation.value,
        inputs.trend.invalidation.available,
    )
    benchmark_is_future = _benchmark_is_future(inputs)
    leadership_gate = _leadership_gate(inputs)
    trend_gate = _trend_gate(inputs, hard_invalidation)
    structure_gate = _structure_gate(inputs)
    liquidity_gate = _liquidity_gate(inputs)
    freshness_gate = _freshness_gate(inputs)
    required_complete = _required_evidence_complete(
        inputs,
        benchmark_is_future,
        gates=(
            leadership_gate,
            trend_gate,
            structure_gate,
            liquidity_gate,
            freshness_gate,
        ),
    )
    score_pillars = _score_pillars(inputs, benchmark_is_future)
    score = _resilience_score(score_pillars)
    correction_survivor = (
        required_complete
        and leadership_gate is True
        and trend_gate is True
        and structure_gate is True
        and liquidity_gate is True
        and freshness_gate is True
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
        inputs,
        hard_invalidation,
        required_complete,
        benchmark_is_future,
        correction_survivor,
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
        market=inputs.provenance.market,
        mic=inputs.provenance.mic,
        as_of_date=inputs.provenance.as_of_date,
        benchmark_symbol=inputs.provenance.benchmark_symbol,
        benchmark_as_of_date=inputs.provenance.benchmark_as_of_date,
    )


def _required_evidence_complete(
    inputs: OpportunityEvidence,
    benchmark_is_future: bool,
    *,
    gates: tuple[bool | None, ...],
) -> bool:
    provenance_complete = (
        bool(inputs.provenance.market)
        and inputs.provenance.as_of_date is not None
        and bool(inputs.provenance.benchmark_symbol)
        and inputs.provenance.benchmark_as_of_date is not None
    )
    event_evidence_complete = (
        inputs.risk.event_risk.available is True
        and inputs.risk.event_risk.value is not None
    )
    return (
        not benchmark_is_future
        and provenance_complete
        and event_evidence_complete
        and all(gate is not None for gate in gates)
    )


def _score_pillars(
    inputs: OpportunityEvidence, benchmark_is_future: bool
) -> dict[str, float | None]:
    if benchmark_is_future or not _score_inputs_known(inputs):
        return {key: None for key in _SCORE_PILLAR_KEYS}

    hard_invalidation = _hard_invalidation(
        inputs.trend.invalidation.value,
        inputs.trend.invalidation.available,
    )
    leadership = float(
        (12 if inputs.leadership.benchmark_relative_return_65d > 0 else 0)
        + (
            8
            if inputs.leadership.rs_line_new_high
            or inputs.leadership.rs_line_blue_dot
            else 0
        )
    )
    multi_horizon = (
        10 * _clamp(inputs.leadership.rs_rating_1m) / 100
        + 10 * _clamp(inputs.leadership.rs_rating_3m) / 100
    )
    trend = float(
        8 * (inputs.trend.stage in (1, 2))
        + 8 * bool(inputs.trend.ma_alignment)
        + 4 * (not hard_invalidation)
    )
    structure = float(
        8 * bool(inputs.structure.primary_pattern.value)
        + 4 * bool(inputs.structure.squeeze)
        + 3 * (inputs.structure.tight_closes_count >= 3)
        + 3 * (inputs.structure.quiet_days_count >= 3)
        + 2
        * (inputs.structure.volume_vs_50d <= inputs.structure.volume_dry_up_max)
    )
    tradability = float(
        10 * bool(inputs.tradability.liquidity.value)
        + 10
        * (
            inputs.tradability.feature_status == "complete"
            and inputs.tradability.is_scannable is True
        )
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


def _score_inputs_known(inputs: OpportunityEvidence) -> bool:
    values = (
        inputs.leadership.benchmark_relative_return_65d,
        inputs.leadership.rs_rating_1m,
        inputs.leadership.rs_rating_3m,
        inputs.leadership.rs_line_new_high,
        inputs.leadership.rs_line_blue_dot,
        inputs.trend.stage,
        inputs.trend.ma_alignment,
        inputs.trend.invalidation.value,
        inputs.structure.squeeze,
        inputs.structure.tight_closes_count,
        inputs.structure.quiet_days_count,
        inputs.structure.volume_vs_50d,
        inputs.structure.volume_dry_up_max,
        inputs.tradability.liquidity.value,
        inputs.tradability.feature_status,
        inputs.tradability.is_scannable,
    )
    return (
        all(value is not None for value in values)
        and inputs.trend.invalidation.available is True
        and inputs.structure.setup_payload_available is True
        and inputs.structure.primary_pattern.available is True
        and inputs.tradability.liquidity.available is True
        and _valid_invalidation_flags(inputs.trend.invalidation.value)
    )


def _leadership_gate(inputs: OpportunityEvidence) -> bool | None:
    benchmark_leadership = (
        None
        if inputs.leadership.benchmark_relative_return_65d is None
        else inputs.leadership.benchmark_relative_return_65d > 0
    )
    rs_line_leadership = _tri_or(
        inputs.leadership.rs_line_new_high,
        inputs.leadership.rs_line_blue_dot,
    )
    one_month = (
        None
        if inputs.leadership.rs_rating_1m is None
        else inputs.leadership.rs_rating_1m >= 80
    )
    three_month = (
        None
        if inputs.leadership.rs_rating_3m is None
        else inputs.leadership.rs_rating_3m >= 70
    )
    return _tri_and(
        _tri_or(benchmark_leadership, rs_line_leadership),
        one_month,
        three_month,
    )


def _trend_gate(inputs: OpportunityEvidence, hard_invalidation: bool | None) -> bool | None:
    stage_passes = None if inputs.trend.stage is None else inputs.trend.stage in (1, 2)
    invalidation_passes = None if hard_invalidation is None else not hard_invalidation
    return _tri_and(stage_passes, inputs.trend.ma_alignment, invalidation_passes)


def _structure_gate(inputs: OpportunityEvidence) -> bool | None:
    pattern_passes = (
        bool(inputs.structure.primary_pattern.value)
        if inputs.structure.primary_pattern.available is True
        else None
    )
    tight_closes_pass = (
        None
        if inputs.structure.tight_closes_count is None
        else inputs.structure.tight_closes_count >= 3
    )
    quiet_days_pass = (
        None
        if inputs.structure.quiet_days_count is None
        else inputs.structure.quiet_days_count >= 3
    )
    dry_up_pass = (
        None
        if inputs.structure.volume_vs_50d is None
        or inputs.structure.volume_dry_up_max is None
        else inputs.structure.volume_vs_50d <= inputs.structure.volume_dry_up_max
    )
    return _tri_or(
        pattern_passes,
        inputs.structure.squeeze,
        tight_closes_pass,
        quiet_days_pass,
        dry_up_pass,
    )


def _liquidity_gate(inputs: OpportunityEvidence) -> bool | None:
    if inputs.tradability.liquidity.available is not True:
        return None
    return inputs.tradability.liquidity.value


def _freshness_gate(inputs: OpportunityEvidence) -> bool | None:
    status_passes = (
        None
        if inputs.tradability.feature_status is None
        else inputs.tradability.feature_status == "complete"
    )
    return _tri_and(status_passes, inputs.tradability.is_scannable)


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


def _benchmark_is_future(inputs: OpportunityEvidence) -> bool:
    return (
        inputs.provenance.as_of_date is not None
        and inputs.provenance.benchmark_as_of_date is not None
        and inputs.provenance.benchmark_as_of_date > inputs.provenance.as_of_date
    )


def _benchmark_is_lagged(inputs: OpportunityEvidence) -> bool:
    return (
        inputs.provenance.as_of_date is not None
        and inputs.provenance.benchmark_as_of_date is not None
        and inputs.provenance.benchmark_as_of_date < inputs.provenance.as_of_date
    )


def _resolve_action_state(
    inputs: OpportunityEvidence,
    hard_invalidation: bool | None,
    required_complete: bool,
    benchmark_is_future: bool,
    correction_survivor: bool,
) -> tuple[ActionState, tuple[str, ...]]:
    if hard_invalidation is True:
        return ActionState.EXIT_RISK, _hard_invalidation_reasons(
            inputs.trend.invalidation.value
        )
    if inputs.risk.event_risk.value is True:
        return ActionState.EVENT_RISK, ("earnings_soon",)
    if inputs.risk.extended is True:
        return ActionState.EXTENDED, ("extended",)
    if not required_complete or inputs.risk.extended is None:
        reasons = ("future_benchmark_date",) if benchmark_is_future else ("required_evidence",)
        return ActionState.DATA_LIMITED, reasons
    if not correction_survivor:
        return ActionState.WATCH, ("watch",)
    setup_ready = _tri_and(inputs.risk.setup_ready, inputs.risk.in_early_zone)
    if setup_ready is None:
        return ActionState.DATA_LIMITED, ("required_evidence",)
    if setup_ready:
        return ActionState.SETUP_READY, ("setup_ready",)
    return ActionState.WATCH, ("watch",)


def _hard_invalidation_reasons(
    flags: tuple[InvalidationEvidence, ...] | None,
) -> tuple[str, ...]:
    if flags is None:
        return ("hard_invalidation",)
    return tuple(f"hard_invalidation:{flag.code}" for flag in flags if flag.is_hard)


def _metrics(inputs: OpportunityEvidence, hard_invalidation: bool | None) -> dict[str, object]:
    return {
        "benchmark_relative_return_65d": inputs.leadership.benchmark_relative_return_65d,
        "rs_rating_1m": inputs.leadership.rs_rating_1m,
        "rs_rating_3m": inputs.leadership.rs_rating_3m,
        "rs_line_new_high": inputs.leadership.rs_line_new_high,
        "rs_line_blue_dot": inputs.leadership.rs_line_blue_dot,
        "stage": inputs.trend.stage,
        "ma_alignment": inputs.trend.ma_alignment,
        "hard_invalidation": hard_invalidation,
        "pattern_primary": inputs.structure.primary_pattern.value,
        "squeeze": inputs.structure.squeeze,
        "tight_closes_count": inputs.structure.tight_closes_count,
        "quiet_days_count": inputs.structure.quiet_days_count,
        "volume_vs_50d": inputs.structure.volume_vs_50d,
        "volume_dry_up_max": inputs.structure.volume_dry_up_max,
        "liquidity_passes": inputs.tradability.liquidity.value,
        "feature_status": inputs.tradability.feature_status,
        "is_scannable": inputs.tradability.is_scannable,
    }


def _data_availability(
    inputs: OpportunityEvidence, required_complete: bool, benchmark_is_future: bool
) -> dict[str, str]:
    return {
        "required_evidence": "complete" if required_complete else "incomplete",
        "benchmark": "future"
        if benchmark_is_future
        else _availability(inputs.provenance.benchmark_as_of_date),
        "invalidation": _availability_flag(
            inputs.trend.invalidation.available
        ),
        "setup": _availability_flag(inputs.structure.setup_payload_available),
        "liquidity": _availability_flag(inputs.tradability.liquidity.available),
        "event_calendar": _availability_flag(inputs.risk.event_risk.available),
        "prior_run": "not_requested",
    }


def _availability(value: object) -> str:
    return "available" if value is not None else "unavailable"


def _availability_flag(value: bool | None) -> str:
    if value is True:
        return "available"
    if value is False:
        return "unavailable"
    return "unknown"


def _record_check(
    passed: list[str],
    failed: list[str],
    name: str,
    condition: bool | None,
) -> None:
    if condition is None:
        return
    (passed if condition else failed).append(name)


def _tri_and(*values: bool | None) -> bool | None:
    if any(value is False for value in values):
        return False
    if all(value is True for value in values):
        return True
    return None


def _tri_or(*values: bool | None) -> bool | None:
    if any(value is True for value in values):
        return True
    if all(value is False for value in values):
        return False
    return None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
