"""Strict wire-contract tests for persisted opportunity-state projections."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.scanning.models import ScanResultItemDomain
from app.schemas.opportunity_state import OpportunityStateResponse
from app.schemas.scanning import ScanResultItem
from app.schemas.user_watchlist import WatchlistStewardshipItem


def _evidence(**changes):
    payload = {
        "schema_version": 1,
        "policy_version": "correction-survivors-v1",
        "as_of_date": "2026-08-21",
        "market": "US",
        "mic": "XNAS",
        "benchmark_symbol": "SPY",
        "benchmark_as_of_date": "2026-08-21",
        "passed_checks": [
            "required_evidence",
            "leadership_gate",
            "trend_gate",
            "structure_gate",
            "liquidity_gate",
            "freshness_gate",
        ],
        "failed_checks": [],
        "warnings": [],
        "score_pillars": {
            "benchmark_leadership": 20.0,
            "multi_horizon_rs": 17.0,
            "trend_integrity": 20.0,
            "structure_tightness": 20.0,
            "liquidity_freshness": 20.0,
        },
        "metrics": {"benchmark_relative_return_65d": 0.08},
        "data_availability": {"required_evidence": "complete"},
        "action_reasons": ["setup_ready"],
    }
    payload.update(changes)
    return payload


def _current_item(**changes):
    payload = {
        "symbol": "CURRENT",
        "rating": "Strong Buy",
        "correction_survivor": True,
        "resilience_score": 97.0,
        "action_state": "setup_ready",
        "opportunity_state": _evidence(),
    }
    payload.update(changes)
    return payload


def _watchlist_item(**changes):
    payload = _current_item(**changes)
    payload.pop("rating")
    payload.update(status="unchanged", reasons=[])
    return payload


def _data_limited_item():
    return _current_item(
        correction_survivor=False,
        resilience_score=None,
        action_state="data_limited",
        opportunity_state=_evidence(
            score_pillars={
                "benchmark_leadership": None,
                "multi_horizon_rs": None,
                "trend_integrity": None,
                "structure_tightness": None,
                "liquidity_freshness": None,
            },
            action_reasons=["required_evidence_missing"],
        ),
    )


SCHEMA_BOUNDARIES = (
    pytest.param(ScanResultItem, _current_item, id="scan-result"),
    pytest.param(WatchlistStewardshipItem, _watchlist_item, id="watchlist-item"),
)


def _domain_item(**extended_fields):
    return ScanResultItemDomain(
        symbol="CURRENT",
        composite_score=90.0,
        rating="Strong Buy",
        current_price=100.0,
        screener_outputs={},
        screeners_run=["minervini"],
        composite_method="weighted_average",
        screeners_passed=1,
        screeners_total=1,
        extended_fields=extended_fields,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value["score_pillars"].update({"sixth_pillar": 1.0}),
        lambda value: value["score_pillars"].pop("trend_integrity"),
        lambda value: value.pop("market"),
    ],
)
def test_opportunity_evidence_requires_exact_canonical_shape(mutation):
    """Break caught: accepting drifted, partial, or augmented versioned evidence."""
    payload = _evidence()
    mutation(payload)

    with pytest.raises(ValidationError):
        OpportunityStateResponse.model_validate(payload)


def test_scan_result_rejects_unknown_action_state_literal():
    """Break caught: a free-form action state crossing the live API boundary."""
    with pytest.raises(ValidationError):
        ScanResultItem.model_validate(_current_item(action_state="future_state"))


@pytest.mark.parametrize(
    "missing_field",
    ["correction_survivor", "resilience_score", "action_state", "opportunity_state"],
)
def test_scan_result_rejects_partially_present_opportunity_projection(missing_field):
    """Break caught: mixed old/new rows masquerading as computed materializations."""
    payload = _current_item()
    payload[missing_field] = None

    with pytest.raises(ValidationError, match="all null|all present"):
        ScanResultItem.model_validate(payload)


@pytest.mark.parametrize(("model", "payload_factory"), SCHEMA_BOUNDARIES)
@pytest.mark.parametrize("present_count", [1, 2, 3])
def test_projection_rejects_partial_explicit_null_keys(
    model,
    payload_factory,
    present_count,
):
    """Break caught: supplied legacy-null fragments being erased by field defaults."""
    payload = {
        "symbol": "LEGACY",
        **(
            {"rating": "Watch"}
            if model is ScanResultItem
            else {"status": "unchanged", "reasons": []}
        ),
    }
    projection_keys = (
        "correction_survivor",
        "resilience_score",
        "action_state",
        "opportunity_state",
    )
    payload.update({key: None for key in projection_keys[:present_count]})

    with pytest.raises(ValidationError, match="all null or all present"):
        model.model_validate(payload)


@pytest.mark.parametrize(("model", "payload_factory"), SCHEMA_BOUNDARIES)
def test_projection_rejects_deleted_key_from_data_limited_computed_row(
    model,
    payload_factory,
):
    """Break caught: a missing nullable score key impersonating a complete computed row."""
    payload = _data_limited_item()
    del payload["resilience_score"]
    if model is WatchlistStewardshipItem:
        payload.pop("rating")
        payload.update(status="unchanged", reasons=[])

    with pytest.raises(ValidationError, match="all null or all present"):
        model.model_validate(payload)


def test_scan_domain_mapper_preserves_partial_projection_presence_for_rejection():
    """Break caught: domain-to-HTTP reconstruction defaulting a supplied null fragment."""
    with pytest.raises(ValidationError, match="all null or all present"):
        ScanResultItem.from_domain(_domain_item(correction_survivor=None))


@pytest.mark.parametrize(("model", "payload_factory"), SCHEMA_BOUNDARIES)
def test_projection_accepts_all_four_explicit_null_keys(model, payload_factory):
    """Break caught: strict presence checks accidentally rejecting explicit legacy nulls."""
    payload = {
        "symbol": "LEGACY",
        "correction_survivor": None,
        "resilience_score": None,
        "action_state": None,
        "opportunity_state": None,
        **(
            {"rating": "Watch"}
            if model is ScanResultItem
            else {"status": "unchanged", "reasons": []}
        ),
    }

    item = model.model_validate(payload)

    assert item.correction_survivor is None
    assert item.resilience_score is None
    assert item.action_state is None
    assert item.opportunity_state is None


def _set_correction_survivor(payload, value):
    payload["correction_survivor"] = value
    if value in (0, "false"):
        payload["action_state"] = "watch"
        payload["opportunity_state"]["action_reasons"] = ["not_setup_ready"]


def _set_resilience_bool(payload, value):
    payload["resilience_score"] = value
    payload["opportunity_state"]["score_pillars"] = {
        "benchmark_leadership": 1 if value else 0,
        "multi_horizon_rs": 0,
        "trend_integrity": 0,
        "structure_tightness": 0,
        "liquidity_freshness": 0,
    }


def _set_pillar_bool(payload, value):
    payload["resilience_score"] = 78 if value else 77
    payload["opportunity_state"]["score_pillars"]["benchmark_leadership"] = value


COERCIVE_PROJECTION_MUTATIONS = (
    pytest.param(lambda payload: _set_correction_survivor(payload, 1), id="survivor-int-one"),
    pytest.param(lambda payload: _set_correction_survivor(payload, 0), id="survivor-int-zero"),
    pytest.param(
        lambda payload: _set_correction_survivor(payload, "true"),
        id="survivor-string-true",
    ),
    pytest.param(
        lambda payload: _set_correction_survivor(payload, "false"),
        id="survivor-string-false",
    ),
    pytest.param(
        lambda payload: payload.update(resilience_score="97.0"),
        id="score-numeric-string",
    ),
    pytest.param(lambda payload: _set_resilience_bool(payload, True), id="score-bool"),
    pytest.param(
        lambda payload: payload["opportunity_state"]["score_pillars"].update(
            benchmark_leadership="20.0"
        ),
        id="pillar-numeric-string",
    ),
    pytest.param(lambda payload: _set_pillar_bool(payload, True), id="pillar-bool"),
)


@pytest.mark.parametrize(("model", "payload_factory"), SCHEMA_BOUNDARIES)
@pytest.mark.parametrize("mutation", COERCIVE_PROJECTION_MUTATIONS)
def test_present_projection_rejects_coercive_json_types(
    model,
    payload_factory,
    mutation,
):
    """Break caught: Pydantic coercion turning malformed JSON into trusted evidence."""
    payload = payload_factory()
    mutation(payload)

    with pytest.raises(ValidationError, match="bool|number"):
        model.model_validate(payload)


@pytest.mark.parametrize(("model", "payload_factory"), SCHEMA_BOUNDARIES)
def test_present_projection_accepts_integer_and_float_scores(model, payload_factory):
    """Break caught: strict primitive checks rejecting ordinary JSON numbers."""
    payload = payload_factory(
        resilience_score=97,
        opportunity_state=_evidence(
            score_pillars={
                "benchmark_leadership": 20,
                "multi_horizon_rs": 17.0,
                "trend_integrity": 20,
                "structure_tightness": 20.0,
                "liquidity_freshness": 20,
            }
        ),
    )

    item = model.model_validate(payload)

    assert item.resilience_score == 97.0


def test_scan_result_accepts_legacy_all_null_projection():
    """Break caught: strict validation accidentally dropping legacy rows."""
    item = ScanResultItem(symbol="LEGACY", rating="Watch")

    assert item.correction_survivor is None
    assert item.resilience_score is None
    assert item.action_state is None
    assert item.opportunity_state is None


def test_scan_result_rejects_score_that_disagrees_with_pillar_sum():
    """Break caught: incoherent top-level score and evidence crossing the API boundary."""
    with pytest.raises(ValidationError, match="pillar sum"):
        ScanResultItem.model_validate(_current_item(resilience_score=96.0))


def test_scan_result_rejects_mixed_null_and_numeric_pillars_for_null_score():
    """Break caught: a partial score being presented as an intentionally unavailable score."""
    evidence = _evidence()
    evidence["score_pillars"] = {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": None,
        "trend_integrity": None,
        "structure_tightness": None,
        "liquidity_freshness": None,
    }

    with pytest.raises(ValidationError, match="all null"):
        ScanResultItem.model_validate(
            _current_item(resilience_score=None, opportunity_state=evidence)
        )


def test_scan_result_accepts_decidable_survivor_with_unavailable_score():
    """Break caught: conflating strict score completeness with tri-state eligibility."""
    evidence = _evidence(
        score_pillars={
            "benchmark_leadership": None,
            "multi_horizon_rs": None,
            "trend_integrity": None,
            "structure_tightness": None,
            "liquidity_freshness": None,
        }
    )
    item = ScanResultItem.model_validate(
        _current_item(resilience_score=None, opportunity_state=evidence)
    )

    assert item.correction_survivor is True
    assert item.action_state == "setup_ready"


def test_scan_result_rejects_setup_ready_for_non_survivor():
    """Break caught: a setup flag bypassing survivor eligibility in a persisted row."""
    with pytest.raises(ValidationError, match="setup_ready"):
        ScanResultItem.model_validate(_current_item(correction_survivor=False))


def test_watchlist_item_uses_the_same_exact_action_state_contract():
    """Break caught: stewardship responses bypassing the canonical action-state literals."""
    payload = _current_item(action_state="future_state")
    payload.pop("rating")
    payload.update(status="unchanged", reasons=[])

    with pytest.raises(ValidationError):
        WatchlistStewardshipItem.model_validate(payload)


def test_watchlist_item_rejects_partial_opportunity_projection():
    """Break caught: one live surface weakening the all-null/all-current invariant."""
    payload = _current_item(opportunity_state=None)
    payload.pop("rating")
    payload.update(status="unchanged", reasons=[])

    with pytest.raises(ValidationError, match="all null|all present"):
        WatchlistStewardshipItem.model_validate(payload)
