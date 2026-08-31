"""Deterministic tests for CAN SLIM V2 score aggregation policy."""

import pytest

from app.scanners.criteria.canslim_v2 import (
    CANSLIMLetter,
    CriterionResult,
    STOCK_SCORE_MAX_POINTS,
    score_market_gate,
)
from app.scanners.criteria.canslim_v2_scorecard import (
    CANSLIMV2Scorecard,
    build_scorecard,
)


def _criterion(
    letter: CANSLIMLetter,
    points: float,
    passes: bool = True,
    available: bool = True,
) -> CriterionResult:
    return CriterionResult(
        letter=letter,
        points=points,
        max_points=STOCK_SCORE_MAX_POINTS[letter],
        passes=passes,
        available=available,
        reason="fixture",
    )


def _passing_scorecard_inputs(market_score: float = 70.0) -> list[CriterionResult]:
    return [
        _criterion(CANSLIMLetter.CURRENT_EARNINGS, 17.0),
        _criterion(CANSLIMLetter.ANNUAL_EARNINGS, 13.0),
        _criterion(CANSLIMLetter.NEW, 10.0),
        _criterion(CANSLIMLetter.SUPPLY_DEMAND, 10.0),
        _criterion(CANSLIMLetter.LEADER, 18.0),
        _criterion(CANSLIMLetter.INSTITUTIONAL, 10.0),
        score_market_gate(exposure_score=market_score),
    ]


def test_scorecard_keeps_market_outside_stock_score() -> None:
    scorecard = build_scorecard(_passing_scorecard_inputs(market_score=90.0))

    assert isinstance(scorecard, CANSLIMV2Scorecard)
    assert scorecard.stock_score == 78.0
    assert scorecard.stock_passes is True
    assert scorecard.market_passes is True
    assert scorecard.actionable is True
    assert scorecard.status == "qualified"


def test_scorecard_market_can_block_qualified_stock_without_changing_score() -> None:
    scorecard = build_scorecard(_passing_scorecard_inputs(market_score=40.0))

    assert scorecard.stock_score == 78.0
    assert scorecard.stock_passes is True
    assert scorecard.market_passes is False
    assert scorecard.actionable is False
    assert scorecard.status == "market_blocked"


def test_scorecard_requires_c_a_and_l_primary_gates() -> None:
    results = _passing_scorecard_inputs()
    results[1] = _criterion(CANSLIMLetter.ANNUAL_EARNINGS, 13.0, passes=False)
    results[2] = _criterion(CANSLIMLetter.NEW, 15.0)
    results[3] = _criterion(CANSLIMLetter.SUPPLY_DEMAND, 15.0)
    results[5] = _criterion(CANSLIMLetter.INSTITUTIONAL, 15.0)

    scorecard = build_scorecard(results)

    assert scorecard.stock_score > 70.0
    assert scorecard.stock_passes is False
    assert scorecard.actionable is False
    assert scorecard.failed_required_letters == ("A",)


def test_scorecard_marks_required_missing_data_explicitly() -> None:
    results = _passing_scorecard_inputs()
    results[0] = _criterion(
        CANSLIMLetter.CURRENT_EARNINGS,
        0.0,
        passes=False,
        available=False,
    )

    scorecard = build_scorecard(results)

    assert scorecard.status == "insufficient_data"
    assert scorecard.unavailable_required_letters == ("C",)
    assert scorecard.actionable is False


def test_scorecard_rejects_missing_or_duplicate_letters() -> None:
    results = _passing_scorecard_inputs()

    with pytest.raises(ValueError, match="Missing CAN SLIM results"):
        build_scorecard(results[:-1])

    with pytest.raises(ValueError, match="Duplicate CAN SLIM result"):
        build_scorecard(results + [results[0]])


def test_scorecard_serialization_preserves_letter_contract() -> None:
    payload = build_scorecard(_passing_scorecard_inputs()).as_dict()

    assert payload["stock_score"] == 78.0
    assert set(payload["criteria"]) == set("CANSLIM")
    assert payload["criteria"]["M"]["max_points"] == 0.0
