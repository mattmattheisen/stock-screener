"""Deterministic unit tests for CAN SLIM V2 criterion primitives."""

import pytest

from app.scanners.criteria.canslim_v2 import (
    CANSLIMLetter,
    CriterionResult,
    METHODOLOGY_VERSION,
    STOCK_SCORE_MAX_POINTS,
    score_annual_earnings,
    score_current_earnings,
)


def test_contract_defines_all_seven_canslim_letters() -> None:
    assert {letter.value for letter in CANSLIMLetter} == set("CANSLIM")
    assert sum(STOCK_SCORE_MAX_POINTS.values()) == 100.0
    assert STOCK_SCORE_MAX_POINTS[CANSLIMLetter.MARKET] == 0.0


def test_contract_rejects_points_outside_criterion_bounds() -> None:
    with pytest.raises(ValueError, match="points must be between"):
        CriterionResult(
            letter=CANSLIMLetter.CURRENT_EARNINGS,
            points=21.0,
            max_points=20.0,
            passes=True,
            available=True,
            reason="invalid",
        )


def test_current_earnings_uses_comparable_quarter_yoy_and_confirmations() -> None:
    result = score_current_earnings(
        eps_yoy=32.0,
        prior_eps_yoy=20.0,
        sales_yoy=27.0,
    )

    assert result.letter is CANSLIMLetter.CURRENT_EARNINGS
    assert result.passes is True
    assert result.available is True
    assert result.points == 17.0
    assert result.metrics["eps_accelerating"] is True
    assert result.metrics["sales_confirmation"] is True


def test_current_earnings_confirmations_cannot_rescue_subthreshold_eps() -> None:
    result = score_current_earnings(
        eps_yoy=20.0,
        prior_eps_yoy=5.0,
        sales_yoy=50.0,
    )

    assert result.passes is False
    assert result.points == 12.0


def test_current_earnings_missing_primary_metric_is_unavailable() -> None:
    result = score_current_earnings(eps_yoy=None, sales_yoy=40.0)

    assert result.available is False
    assert result.passes is False
    assert result.points == 0.0


def test_annual_earnings_requires_multi_year_history() -> None:
    result = score_annual_earnings(
        eps_cagr=35.0,
        years_available=3,
        eps_rating=95.0,
        roe=30.0,
    )

    assert result.available is False
    assert result.passes is False
    assert result.points == 0.0


def test_annual_earnings_scores_growth_with_optional_quality_confirmations() -> None:
    result = score_annual_earnings(
        eps_cagr=35.0,
        years_available=5,
        eps_rating=90.0,
        roe=20.0,
    )

    assert result.available is True
    assert result.passes is True
    assert result.points == 15.0
    assert result.metrics["eps_rating_confirmation"] is True
    assert result.metrics["roe_confirmation"] is True


def test_annual_earnings_below_growth_gate_does_not_pass() -> None:
    result = score_annual_earnings(
        eps_cagr=18.0,
        years_available=5,
        eps_rating=90.0,
        roe=20.0,
    )

    assert result.available is True
    assert result.passes is False
    assert result.points == 11.0


def test_contract_serialization_is_api_friendly() -> None:
    result = score_current_earnings(eps_yoy=25.0)
    payload = result.as_dict()

    assert payload["letter"] == "C"
    assert payload["methodology_version"] == METHODOLOGY_VERSION
    assert payload["max_points"] == 20.0
