from datetime import date, datetime, timezone

import pytest

import app.domain.scanning.opportunity_state as opportunity_state
from app.domain.scanning.opportunity_state import (
    ActionState,
    InvalidationEvidence,
    evaluate_opportunity_state,
    normalize_event_date,
    opportunity_result_from_projection,
    overlay_stewardship_state,
    serialize_opportunity_projection,
)


def test_domain_exposes_grouped_opportunity_evidence_boundary():
    """Break caught: policy inputs collapsing back into one flat field bag."""
    assert hasattr(opportunity_state, "OpportunityEvidence")
    assert hasattr(opportunity_state, "LeadershipEvidence")
    assert hasattr(opportunity_state, "StructureEvidence")
    assert hasattr(opportunity_state, "TrendEvidence")
    assert hasattr(opportunity_state, "TradabilityEvidence")
    assert hasattr(opportunity_state, "RiskEvidence")
    assert hasattr(opportunity_state, "EvidenceValue")


def test_policy_evaluates_grouped_evidence_without_flat_input_bag():
    """Break caught: the policy still depending on the 35-field OpportunityInputs bag."""
    evidence = opportunity_state.OpportunityEvidence(
        provenance=opportunity_state.ProvenanceEvidence(
            market="US",
            mic="XNAS",
            as_of_date=date(2026, 8, 21),
            benchmark_symbol="SPY",
            benchmark_as_of_date=date(2026, 8, 21),
        ),
        leadership=opportunity_state.LeadershipEvidence(
            benchmark_relative_return_65d=0.08,
            rs_rating_1m=90.0,
            rs_rating_3m=80.0,
            rs_line_new_high=True,
            rs_line_blue_dot=False,
        ),
        trend=opportunity_state.TrendEvidence(
            stage=2,
            ma_alignment=True,
            invalidation=opportunity_state.EvidenceValue((), True),
        ),
        structure=opportunity_state.StructureEvidence(
            setup_payload_available=True,
            primary_pattern=opportunity_state.EvidenceValue("vcp", True),
            squeeze=True,
            tight_closes_count=3,
            quiet_days_count=3,
            volume_vs_50d=0.70,
            volume_dry_up_max=0.80,
        ),
        tradability=opportunity_state.TradabilityEvidence(
            liquidity=opportunity_state.EvidenceValue(True, True),
            feature_status="complete",
            is_scannable=True,
        ),
        risk=opportunity_state.RiskEvidence(
            event_risk=opportunity_state.EvidenceValue(False, True),
            setup_ready=True,
            in_early_zone=True,
            extended=False,
        ),
    )

    result = evaluate_opportunity_state(evidence)

    assert result.correction_survivor is True
    assert result.resilience_score == 97.0
    assert result.action_state is ActionState.SETUP_READY


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
        "pattern_primary_available": True,
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
    }
    values.update(changes)
    return opportunity_state.OpportunityEvidence(
        provenance=opportunity_state.ProvenanceEvidence(
            market=values["market"],
            mic=values["mic"],
            as_of_date=values["as_of_date"],
            benchmark_symbol=values["benchmark_symbol"],
            benchmark_as_of_date=values["benchmark_as_of_date"],
        ),
        leadership=opportunity_state.LeadershipEvidence(
            benchmark_relative_return_65d=values["benchmark_relative_return_65d"],
            rs_rating_1m=values["rs_rating_1m"],
            rs_rating_3m=values["rs_rating_3m"],
            rs_line_new_high=values["rs_line_new_high"],
            rs_line_blue_dot=values["rs_line_blue_dot"],
        ),
        trend=opportunity_state.TrendEvidence(
            stage=values["stage"],
            ma_alignment=values["ma_alignment"],
            invalidation=opportunity_state.EvidenceValue(
                values["invalidation_flags"],
                values["invalidation_evidence_available"],
            ),
        ),
        structure=opportunity_state.StructureEvidence(
            setup_payload_available=values["setup_payload_available"],
            primary_pattern=opportunity_state.EvidenceValue(
                values["pattern_primary"],
                values["pattern_primary_available"],
            ),
            squeeze=values["squeeze"],
            tight_closes_count=values["tight_closes_count"],
            quiet_days_count=values["quiet_days_count"],
            volume_vs_50d=values["volume_vs_50d"],
            volume_dry_up_max=values["volume_dry_up_max"],
        ),
        tradability=opportunity_state.TradabilityEvidence(
            liquidity=opportunity_state.EvidenceValue(
                values["liquidity_passes"],
                values["liquidity_available"],
            ),
            feature_status=values["feature_status"],
            is_scannable=values["is_scannable"],
        ),
        risk=opportunity_state.RiskEvidence(
            event_risk=opportunity_state.EvidenceValue(
                values["earnings_soon"],
                values["event_calendar_available"],
            ),
            setup_ready=values["setup_ready"],
            in_early_zone=values["in_early_zone"],
            extended=values["extended"],
        ),
    )


def test_complete_survivor_has_exact_score_and_setup_ready_state():
    """Break caught: changing a pillar weight or ready-state branch misranks a complete setup."""
    result = evaluate_opportunity_state(complete_inputs())

    assert result.correction_survivor is True
    assert result.resilience_score == 97.0
    assert result.action_state is ActionState.SETUP_READY


def test_assessment_metrics_are_immutable_and_enriched_by_copy():
    """Break caught: application services mutating serialized or assessed evidence in place."""
    result = evaluate_opportunity_state(complete_inputs())

    with pytest.raises(TypeError):
        result.metrics["liquidity_floor_local"] = 1_000_000

    enriched = result.with_metrics({"liquidity_floor_local": 1_000_000})

    assert "liquidity_floor_local" not in result.metrics
    assert enriched.metrics["liquidity_floor_local"] == 1_000_000


def test_complete_survivor_persists_the_five_canonical_score_pillars():
    """Break caught: a persisted row omits its backend-calculated pillar totals."""
    projection = serialize_opportunity_projection(
        evaluate_opportunity_state(complete_inputs())
    )

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
                "earnings_soon": True,
                "extended": True,
                "event_calendar_available": False,
                "setup_ready": False,
            },
            ActionState.EXIT_RISK,
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
    ("field", "value", "expected_survivor"),
    [
        ("benchmark_relative_return_65d", None, True),
        ("rs_rating_1m", None, False),
        ("rs_rating_3m", None, False),
        ("rs_line_new_high", None, True),
        ("rs_line_blue_dot", None, True),
        ("stage", None, False),
        ("ma_alignment", None, False),
        ("invalidation_flags", None, False),
        ("pattern_primary_available", False, True),
        ("squeeze", None, True),
        ("tight_closes_count", None, True),
        ("quiet_days_count", None, True),
        ("volume_vs_50d", None, True),
        ("volume_dry_up_max", None, True),
        ("liquidity_passes", None, False),
        ("feature_status", None, False),
        ("is_scannable", None, False),
    ],
)
def test_missing_score_input_never_coerces_to_zero(field, value, expected_survivor):
    """Break caught: replacing an unknown score input with a false or zero contribution."""
    result = evaluate_opportunity_state(complete_inputs(**{field: value}))

    assert result.resilience_score is None
    assert result.correction_survivor is expected_survivor


@pytest.mark.parametrize(
    "changes",
    [
        {
            "benchmark_relative_return_65d": 0.0,
            "rs_line_new_high": False,
            "rs_line_blue_dot": False,
        },
        {"rs_rating_1m": 79.9},
        {"rs_rating_3m": 69.9},
    ],
)
def test_each_leadership_gate_boundary_can_disqualify_a_complete_row(changes):
    """Break caught: treating a weak leadership component as eligible merely because a score exists."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.resilience_score is not None
    assert result.correction_survivor is False
    assert "leadership_gate" in result.failed_checks


@pytest.mark.parametrize(
    ("changes", "expected_score"),
    [
        (
            {"rs_line_new_high": False, "rs_line_blue_dot": False},
            89.0,
        ),
        (
            {"benchmark_relative_return_65d": -0.01},
            85.0,
        ),
        (
            {"rs_rating_1m": 80.0, "rs_rating_3m": 70.0},
            95.0,
        ),
    ],
)
def test_leadership_gate_uses_or_signal_and_exact_rs_boundaries(changes, expected_score):
    """Break caught: requiring both benchmark return and RS-line leadership, or using RS 70 for 1M."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is True
    assert result.resilience_score == expected_score
    assert result.action_state is ActionState.SETUP_READY


def test_positive_return_decides_leadership_when_rs_line_signals_are_unknown():
    """Break caught: score completeness incorrectly making a decidable leadership gate unavailable."""
    result = evaluate_opportunity_state(
        complete_inputs(rs_line_new_high=None, rs_line_blue_dot=None)
    )

    assert result.correction_survivor is True
    assert result.resilience_score is None
    assert result.action_state is ActionState.SETUP_READY


def test_leadership_is_unknown_when_no_known_disjunct_passes():
    """Break caught: coercing a missing RS-line signal to false and reporting a definitive gate failure."""
    result = evaluate_opportunity_state(
        complete_inputs(
            benchmark_relative_return_65d=-0.01,
            rs_line_new_high=None,
            rs_line_blue_dot=False,
        )
    )

    assert result.correction_survivor is False
    assert result.resilience_score is None
    assert result.action_state is ActionState.DATA_LIMITED
    assert "leadership_gate" not in result.failed_checks


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


def test_primary_pattern_alone_decides_constructive_structure():
    """Break caught: requiring every supported structure signal instead of any one passing signal."""
    result = evaluate_opportunity_state(
        complete_inputs(
            squeeze=False,
            tight_closes_count=2,
            quiet_days_count=2,
            volume_vs_50d=0.81,
        )
    )

    assert result.correction_survivor is True
    assert result.resilience_score == 85.0
    assert result.action_state is ActionState.SETUP_READY


def test_primary_pattern_decides_structure_when_other_signals_are_unknown():
    """Break caught: all-input score completeness leaking into the any-signal structure gate."""
    result = evaluate_opportunity_state(
        complete_inputs(
            squeeze=None,
            tight_closes_count=None,
            quiet_days_count=None,
            volume_vs_50d=None,
        )
    )

    assert result.correction_survivor is True
    assert result.resilience_score is None
    assert result.action_state is ActionState.SETUP_READY


def test_present_null_primary_pattern_is_known_false_with_alternate_structure_pass():
    """Break caught: present-null pattern evidence preventing an otherwise complete score."""
    result = evaluate_opportunity_state(
        complete_inputs(
            pattern_primary=None,
            pattern_primary_available=True,
        )
    )

    assert result.correction_survivor is True
    assert result.resilience_score == 89.0
    assert result.action_state is ActionState.SETUP_READY
    assert result.metrics["pattern_primary"] is None


def test_present_null_primary_pattern_and_failed_alternates_is_known_structure_failure():
    """Break caught: known absence becoming data-limited instead of a failed structure gate."""
    result = evaluate_opportunity_state(
        complete_inputs(
            pattern_primary=None,
            pattern_primary_available=True,
            squeeze=False,
            tight_closes_count=2,
            quiet_days_count=2,
            volume_vs_50d=0.81,
        )
    )

    assert result.correction_survivor is False
    assert result.resilience_score == 77.0
    assert result.action_state is ActionState.WATCH
    assert "structure_gate" in result.failed_checks
    assert result.metrics["pattern_primary"] is None


def test_unavailable_primary_pattern_remains_unknown_when_alternates_fail():
    """Break caught: missing primary-pattern evidence being coerced to a false score input."""
    result = evaluate_opportunity_state(
        complete_inputs(
            pattern_primary=None,
            pattern_primary_available=False,
            squeeze=False,
            tight_closes_count=2,
            quiet_days_count=2,
            volume_vs_50d=0.81,
        )
    )

    assert result.correction_survivor is False
    assert result.resilience_score is None
    assert result.action_state is ActionState.DATA_LIMITED
    assert "structure_gate" not in result.failed_checks


def test_all_known_structure_failures_make_the_row_ineligible():
    """Break caught: an any-signal structure gate passing when every supported signal fails."""
    result = evaluate_opportunity_state(
        complete_inputs(
            pattern_primary=None,
            squeeze=False,
            tight_closes_count=2,
            quiet_days_count=2,
            volume_vs_50d=0.81,
        )
    )

    assert result.correction_survivor is False
    assert "structure_gate" in result.failed_checks
    assert result.action_state is ActionState.WATCH


def test_structure_is_unknown_when_remaining_signal_is_missing():
    """Break caught: a missing supported structure signal silently becoming a known failure."""
    result = evaluate_opportunity_state(
        complete_inputs(
            pattern_primary=None,
            pattern_primary_available=False,
            squeeze=False,
            tight_closes_count=2,
            quiet_days_count=2,
            volume_vs_50d=0.81,
        )
    )

    assert result.correction_survivor is False
    assert result.action_state is ActionState.DATA_LIMITED
    assert "structure_gate" not in result.failed_checks


def test_known_liquidity_failure_can_disqualify_a_complete_row():
    """Break caught: permitting unverified or failed liquidity to pass eligibility."""
    result = evaluate_opportunity_state(complete_inputs(liquidity_passes=False))

    assert result.correction_survivor is False
    assert "liquidity_gate" in result.failed_checks


def test_unavailable_liquidity_is_unknown_not_a_definitive_failure():
    """Break caught: recording unavailable liquidity evidence as a known failed gate."""
    result = evaluate_opportunity_state(complete_inputs(liquidity_available=False))

    assert result.correction_survivor is False
    assert result.action_state is ActionState.DATA_LIMITED
    assert "liquidity_gate" not in result.failed_checks


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
        {"event_calendar_available": False},
    ],
)
def test_each_required_evidence_boundary_marks_a_row_data_limited(changes):
    """Break caught: allowing unavailable required evidence to silently satisfy eligibility."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert result.action_state is ActionState.DATA_LIMITED
    assert "required_evidence" in result.failed_checks


def test_setup_payload_availability_does_not_override_decidable_survivor_gates():
    """Break caught: treating score-only completeness evidence as an eligibility gate."""
    result = evaluate_opportunity_state(complete_inputs(setup_payload_available=False))

    assert result.correction_survivor is True
    assert result.resilience_score is None
    assert result.action_state is ActionState.SETUP_READY


@pytest.mark.parametrize("changes", [{"market": None}, {"as_of_date": None}])
def test_market_and_as_of_provenance_are_required(changes):
    """Break caught: classifying a survivor without its Market or point-in-time row date."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert result.action_state is ActionState.DATA_LIMITED
    assert "required_evidence" in result.failed_checks


@pytest.mark.parametrize(
    "changes",
    [
        {
            "benchmark_relative_return_65d": 0.0,
            "rs_line_new_high": False,
            "rs_line_blue_dot": False,
        },
        {"rs_rating_1m": 75.0},
        {"rs_rating_3m": 65.0},
        {"stage": 3},
        {"ma_alignment": False},
        {
            "pattern_primary": None,
            "squeeze": False,
            "tight_closes_count": 2,
            "quiet_days_count": 2,
            "volume_vs_50d": 0.81,
        },
        {"liquidity_passes": False},
        {"feature_status": "partial"},
        {"is_scannable": False},
    ],
)
def test_known_eligibility_failures_cannot_resolve_setup_ready(changes):
    """Break caught: Setup Engine readiness bypassing a known failed survivor gate."""
    result = evaluate_opportunity_state(complete_inputs(**changes))

    assert result.correction_survivor is False
    assert result.action_state is ActionState.WATCH


def test_projection_round_trip_preserves_typed_state():
    """Break caught: serializing a typed result into a projection that cannot be restored exactly."""
    original = evaluate_opportunity_state(complete_inputs())
    restored = opportunity_result_from_projection(
        serialize_opportunity_projection(original)
    )

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
    projection = serialize_opportunity_projection(
        evaluate_opportunity_state(complete_inputs())
    )
    projection["action_state"] = "not-a-real-state"

    with pytest.raises(ValueError, match="action_state"):
        opportunity_result_from_projection(projection)


def test_present_projection_rejects_missing_required_evidence_key():
    """Break caught: accepting a truncated present payload as if omitted metadata were a null value."""
    projection = serialize_opportunity_projection(
        evaluate_opportunity_state(complete_inputs())
    )
    del projection["opportunity_state"]["market"]

    with pytest.raises(ValueError, match="market"):
        opportunity_result_from_projection(projection)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda projection: projection.update({"unexpected": True}),
        lambda projection: projection["opportunity_state"].update({"unexpected": True}),
        lambda projection: projection["opportunity_state"]["score_pillars"].update(
            {"unexpected": 1.0}
        ),
    ],
)
def test_present_projection_rejects_unknown_versioned_keys(mutation):
    """Break caught: silently ignoring schema drift in persisted policy evidence."""
    projection = serialize_opportunity_projection(
        evaluate_opportunity_state(complete_inputs())
    )
    mutation(projection)

    with pytest.raises(ValueError, match="unexpected"):
        opportunity_result_from_projection(projection)


def test_present_projection_rejects_partial_top_level_materialization():
    """Break caught: interpreting a mixed legacy/current row as not computed."""
    with pytest.raises(ValueError, match="all null or all present"):
        opportunity_result_from_projection({"correction_survivor": True})


def test_present_projection_rejects_incoherent_score_sum():
    """Break caught: trusting a score that disagrees with its persisted decomposition."""
    projection = serialize_opportunity_projection(
        evaluate_opportunity_state(complete_inputs())
    )
    projection["resilience_score"] = 96.0

    with pytest.raises(ValueError, match="pillar sum"):
        opportunity_result_from_projection(projection)


def test_present_projection_rejects_setup_ready_non_survivor():
    """Break caught: accepting an impossible action/eligibility combination from storage."""
    projection = serialize_opportunity_projection(
        evaluate_opportunity_state(complete_inputs())
    )
    projection["correction_survivor"] = False

    with pytest.raises(ValueError, match="setup_ready"):
        opportunity_result_from_projection(projection)


def test_stewardship_exit_risk_outranks_persisted_setup_ready_state():
    """Break caught: allowing a current exit signal to be ignored by a lower persisted ready state."""
    original = evaluate_opportunity_state(complete_inputs())
    overlaid = overlay_stewardship_state(original, "exit_risk", prior_run_available=True)

    assert overlaid.action_state is ActionState.EXIT_RISK
    assert overlaid.action_reasons[-1] == "stewardship_exit_risk"
    assert overlaid.metrics == original.metrics
    assert overlaid.data_availability["prior_run"] == "available"


def test_stewardship_exit_risk_overlays_without_prior_run_evidence():
    """Break caught: prior-gating exit risk derived entirely from current evidence."""
    original = evaluate_opportunity_state(complete_inputs())
    overlaid = overlay_stewardship_state(
        original,
        "exit_risk",
        prior_run_available=False,
    )

    assert overlaid.action_state is ActionState.EXIT_RISK
    assert overlaid.action_reasons[-1] == "stewardship_exit_risk"
    assert overlaid.data_availability["prior_run"] == "unavailable"


def test_stewardship_deteriorating_records_prior_run_as_available():
    original = evaluate_opportunity_state(complete_inputs())

    overlaid = overlay_stewardship_state(
        original,
        "deteriorating",
        prior_run_available=True,
    )

    assert overlaid.action_state is ActionState.DETERIORATING
    assert overlaid.data_availability["prior_run"] == "available"


def test_stewardship_deteriorating_requires_prior_run_evidence():
    """Break caught: inventing a genuinely cross-run deterioration without a prior row."""
    original = evaluate_opportunity_state(complete_inputs())

    assert (
        overlay_stewardship_state(
            original,
            "deteriorating",
            prior_run_available=False,
        )
        is original
    )


def test_no_prior_exit_overlay_preserves_equal_persisted_exit_risk():
    """Break caught: replacing an equal-precedence persisted state during current overlay."""
    original = evaluate_opportunity_state(
        complete_inputs(
            invalidation_flags=(InvalidationEvidence("failed_base", True),),
        )
    )

    assert (
        overlay_stewardship_state(
            original,
            "exit_risk",
            prior_run_available=False,
        )
        is original
    )


def test_lower_priority_stewardship_state_leaves_result_unchanged():
    """Break caught: overwriting a stronger persisted state with a weaker stewardship classification."""
    original = evaluate_opportunity_state(complete_inputs(extended=True))

    assert overlay_stewardship_state(original, "watch", prior_run_available=True) is original
