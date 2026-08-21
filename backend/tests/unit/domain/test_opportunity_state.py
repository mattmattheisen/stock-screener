from datetime import date, datetime, timezone

import pytest

from app.domain.scanning.opportunity_state import (
    ActionState,
    InvalidationEvidence,
    OpportunityInputs,
    evaluate_opportunity_state,
    normalize_event_date,
    opportunity_result_from_projection,
    overlay_stewardship_state,
)


def complete_inputs(**changes):
    values = {
        "market": "US",
        "mic": "XNAS",
        "as_of_date": date(2026, 8, 21),
        "benchmark_symbol": "SPY",
        "benchmark_as_of_date": date(2026, 8, 21),
        "benchmark_relative_return_65d": 0.08,
        "rs_rating_1m": 90.0,
        "rs_rating_3m": 80.0,
        "rs_line_new_high": True,
        "rs_line_blue_dot": False,
        "stage": 2,
        "ma_alignment": True,
        "invalidation_evidence_available": True,
        "invalidation_flags": (),
        "setup_payload_available": True,
        "pattern_primary": "vcp",
        "squeeze": True,
        "tight_closes_count": 3,
        "quiet_days_count": 3,
        "volume_vs_50d": 0.70,
        "volume_dry_up_max": 0.80,
        "liquidity_available": True,
        "liquidity_passes": True,
        "feature_status": "complete",
        "is_scannable": True,
        "event_calendar_available": True,
        "earnings_soon": False,
        "setup_ready": True,
        "in_early_zone": True,
        "extended": False,
        "prior_run_required": False,
        "prior_run_available": False,
        "deterioration_confirmed": False,
        "stewardship_status": None,
    }
    values.update(changes)
    return OpportunityInputs(**values)


def test_complete_survivor_has_exact_score_and_setup_ready_state():
    """Break caught: changing a pillar weight or ready-state branch misranks a complete setup."""
    result = evaluate_opportunity_state(complete_inputs())

    assert result.correction_survivor is True
    assert result.resilience_score == 97.0
    assert result.action_state is ActionState.SETUP_READY


def test_complete_survivor_persists_the_five_canonical_score_pillars():
    """Break caught: a persisted row omits its backend-calculated pillar totals."""
    projection = evaluate_opportunity_state(complete_inputs()).projection()

    assert projection["opportunity_state"]["score_pillars"] == {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 17.0,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"invalidation_flags": (InvalidationEvidence("breaks_50d_support", True),)}, ActionState.EXIT_RISK),
        ({"deterioration_confirmed": True}, ActionState.DETERIORATING),
        ({"earnings_soon": True}, ActionState.EVENT_RISK),
        ({"extended": True}, ActionState.EXTENDED),
        ({"event_calendar_available": False}, ActionState.DATA_LIMITED),
        ({"setup_ready": False}, ActionState.WATCH),
    ],
)
def test_action_state_precedence(changes, expected):
    """Break caught: resolving a lower-priority state before a known higher-priority risk."""
    assert evaluate_opportunity_state(complete_inputs(**changes)).action_state is expected


def test_higher_precedence_known_risk_wins_over_missing_data():
    """Break caught: treating missing evidence as stronger than a confirmed hard invalidation."""
    inputs = complete_inputs(
        event_calendar_available=False,
        invalidation_flags=(InvalidationEvidence("breaks_50d_support", True),),
    )
    assert evaluate_opportunity_state(inputs).action_state is ActionState.EXIT_RISK


def test_missing_invalidation_evidence_remains_unknown_in_metrics():
    """Break caught: serializing unavailable invalidation evidence as a known no-risk flag."""
    result = evaluate_opportunity_state(
        complete_inputs(invalidation_evidence_available=False, invalidation_flags=None)
    )

    assert result.action_state is ActionState.DATA_LIMITED
    assert result.metrics["hard_invalidation"] is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {
                "invalidation_flags": (InvalidationEvidence("failed_base", True),),
                "deterioration_confirmed": True,
                "earnings_soon": True,
                "extended": True,
                "event_calendar_available": False,
                "setup_ready": False,
            },
            ActionState.EXIT_RISK,
        ),
        (
            {
                "deterioration_confirmed": True,
                "earnings_soon": True,
                "extended": True,
                "event_calendar_available": False,
                "setup_ready": False,
            },
            ActionState.DETERIORATING,
        ),
        (
            {
                "earnings_soon": True,
                "extended": True,
                "event_calendar_available": False,
                "setup_ready": False,
            },
            ActionState.EVENT_RISK,
        ),
        (
            {"extended": True, "event_calendar_available": False, "setup_ready": False},
            ActionState.EXTENDED,
        ),
        ({"event_calendar_available": False, "setup_ready": False}, ActionState.DATA_LIMITED),
    ],
)
def test_each_higher_action_state_wins_its_lower_precedence_collisions(changes, expected):
    """Break caught: a lower action-state branch preempting a simultaneous higher-priority branch."""
    assert evaluate_opportunity_state(complete_inputs(**changes)).action_state is expected


@pytest.mark.parametrize(
    ("raw", "key_present", "expected"),
    [
        ("2026-09-01", True, (date(2026, 9, 1), True, None)),
        (
            datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc),
            True,
            (date(2026, 9, 1), True, None),
        ),
        (None, True, (None, True, None)),
        (None, False, (None, False, "missing_event_calendar")),
        ("not-a-date", True, (None, False, "invalid_next_earnings_date")),
    ],
)
def test_event_date_normalization_preserves_unknown_vs_no_event(raw, key_present, expected):
    """Break caught: coercing absent or malformed event evidence into a known no-event value."""
    normalized = normalize_event_date(raw, key_present=key_present)

    assert (normalized.value, normalized.available, normalized.reason) == expected


def test_future_benchmark_date_is_rejected_as_data_limited():
    """Break caught: allowing future benchmark data to influence a point-in-time decision."""
    result = evaluate_opportunity_state(complete_inputs(benchmark_as_of_date=date(2026, 8, 22)))

    assert result.correction_survivor is False
    assert result.resilience_score is None
    assert result.action_state is ActionState.DATA_LIMITED
    assert "future_benchmark_date" in result.failed_checks


def test_non_future_benchmark_lag_is_admissible_and_auditable():
    """Break caught: rejecting exchange-holiday lag instead of recording it for audit."""
    result = evaluate_opportunity_state(complete_inputs(benchmark_as_of_date=date(2026, 8, 20)))

    assert result.correction_survivor is True
    assert result.resilience_score == 97.0
    assert "benchmark_date_lag" in result.warnings


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("benchmark_relative_return_65d", None),
        ("rs_rating_1m", None),
        ("rs_rating_3m", None),
        ("rs_line_new_high", None),
        ("rs_line_blue_dot", None),
        ("stage", None),
        ("ma_alignment", None),
        ("invalidation_flags", None),
        ("pattern_primary", None),
        ("squeeze", None),
        ("tight_closes_count", None),
        ("quiet_days_count", None),
        ("volume_vs_50d", None),
        ("volume_dry_up_max", None),
        ("liquidity_passes", None),
        ("feature_status", None),
        ("is_scannable", None),
    ],
)
def test_missing_score_input_never_coerces_to_zero(field, value):
    """Break caught: replacing an unknown score input with a false or zero contribution."""
    result = evaluate_opportunity_state(complete_inputs(**{field: value}))

    assert result.resilience_score is None
    assert result.correction_survivor is False


@pytest.mark.parametrize(
    "changes",
    [
        {"benchmark_relative_return_65d": 0.0},
        {"rs_rating_1m": 69.9},
        {"rs_rating_3m": 69.9},
        {"rs_line_new_high": False, "rs_line_blue_dot": False},
    ],
)
def test_each_leadership_gate_boundary_can_disqualify_a_complete_row(changes):
    """Break caught: treating a weak leadership component as eligible merely because a score exists."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.resilience_score is not None
    assert result.correction_survivor is False
    assert "leadership_gate" in result.failed_checks


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": 3},
        {"ma_alignment": False},
        {"invalidation_flags": (InvalidationEvidence("failed_base", True),)},
    ],
)
def test_each_trend_gate_boundary_can_disqualify_a_complete_row(changes):
    """Break caught: allowing a failed trend condition to be rescued by other pillars."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert "trend_gate" in result.failed_checks


@pytest.mark.parametrize(
    "changes",
    [
        {"pattern_primary": ""},
        {"squeeze": False},
        {"tight_closes_count": 2},
        {"quiet_days_count": 2},
        {"volume_vs_50d": 0.81},
    ],
)
def test_each_structure_gate_boundary_can_disqualify_a_complete_row(changes):
    """Break caught: classifying an incomplete contraction setup as a survivor."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert "structure_gate" in result.failed_checks


@pytest.mark.parametrize(
    "changes",
    [
        {"liquidity_available": False},
        {"liquidity_passes": False},
    ],
)
def test_each_liquidity_gate_boundary_can_disqualify_a_complete_row(changes):
    """Break caught: permitting unverified or failed liquidity to pass eligibility."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert "liquidity_gate" in result.failed_checks


@pytest.mark.parametrize("changes", [{"feature_status": "partial"}, {"is_scannable": False}])
def test_each_freshness_gate_boundary_can_disqualify_a_complete_row(changes):
    """Break caught: accepting stale or unscannable feature data as fresh."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert "freshness_gate" in result.failed_checks


@pytest.mark.parametrize(
    "changes",
    [
        {"invalidation_evidence_available": False},
        {"setup_payload_available": False},
        {"event_calendar_available": False},
        {"prior_run_required": True, "prior_run_available": False},
    ],
)
def test_each_required_evidence_boundary_marks_a_row_data_limited(changes):
    """Break caught: allowing unavailable required evidence to silently satisfy eligibility."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert result.action_state is ActionState.DATA_LIMITED
    assert "required_evidence" in result.failed_checks


def test_current_only_row_ignores_absent_prior_run_data():
    """Break caught: requiring cross-run evidence for a current-only state calculation."""
    result = evaluate_opportunity_state(complete_inputs(prior_run_required=False, prior_run_available=False))

    assert result.correction_survivor is True
    assert result.action_state is ActionState.SETUP_READY


def test_projection_round_trip_preserves_typed_state():
    """Break caught: serializing a typed result into a projection that cannot be restored exactly."""
    original = evaluate_opportunity_state(complete_inputs())
    restored = opportunity_result_from_projection(original.projection())

    assert restored == original
    assert restored.action_state is ActionState.SETUP_READY
    assert restored.score_pillars == {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 17.0,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    }


def test_absent_legacy_projection_is_ignored():
    """Break caught: rejecting old rows that never carried an opportunity-state payload."""
    assert opportunity_result_from_projection({"symbol": "AAPL"}) is None
    assert opportunity_result_from_projection(None) is None


def test_malformed_present_projection_is_rejected():
    """Break caught: accepting a present but invalid persisted action state as trusted evidence."""
    projection = evaluate_opportunity_state(complete_inputs()).projection()
    projection["action_state"] = "not-a-real-state"

    with pytest.raises(ValueError, match="action_state"):
        opportunity_result_from_projection(projection)


def test_present_projection_rejects_missing_required_evidence_key():
    """Break caught: accepting a truncated present payload as if omitted metadata were a null value."""
    projection = evaluate_opportunity_state(complete_inputs()).projection()
    del projection["opportunity_state"]["market"]

    with pytest.raises(ValueError, match="market"):
        opportunity_result_from_projection(projection)


def test_stewardship_exit_risk_outranks_persisted_setup_ready_state():
    """Break caught: allowing a cross-run exit signal to be ignored by a lower persisted ready state."""
    original = evaluate_opportunity_state(complete_inputs())
    overlaid = overlay_stewardship_state(original, "exit_risk", prior_run_available=True)

    assert overlaid.action_state is ActionState.EXIT_RISK
    assert overlaid.action_reasons[-1] == "stewardship_exit_risk"
    assert overlaid.metrics == original.metrics


def test_stewardship_overlay_requires_prior_run_evidence():
    """Break caught: applying a cross-run stewardship state when no prior run was requested or available."""
    original = evaluate_opportunity_state(complete_inputs())

    assert overlay_stewardship_state(original, "exit_risk", prior_run_available=False) is original


def test_lower_priority_stewardship_state_leaves_result_unchanged():
    """Break caught: overwriting a stronger persisted state with a weaker stewardship classification."""
    original = evaluate_opportunity_state(complete_inputs(extended=True))

    assert overlay_stewardship_state(original, "watch", prior_run_available=True) is original
