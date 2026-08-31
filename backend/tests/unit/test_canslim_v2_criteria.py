"""Deterministic unit tests for CAN SLIM V2 criterion primitives."""

import pytest

from app.scanners.criteria.canslim_v2 import (
    CANSLIMLetter,
    CriterionResult,
    METHODOLOGY_VERSION,
    STOCK_SCORE_MAX_POINTS,
    score_annual_earnings,
    score_current_earnings,
    score_institutional_sponsorship,
    score_leader,
    score_market_gate,
    score_new_highs,
    score_supply_demand,
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


def test_new_highs_uses_price_leadership_with_confirmations() -> None:
    result = score_new_highs(
        distance_from_52w_high_pct=4.0,
        catalyst_recent=True,
        breakout_volume_ratio=1.8,
    )

    assert result.passes is True
    assert result.points == 14.0
    assert result.metrics["catalyst_confirmation"] is True
    assert result.metrics["volume_confirmation"] is True


def test_new_highs_confirmations_cannot_rescue_stock_far_from_high() -> None:
    result = score_new_highs(
        distance_from_52w_high_pct=18.0,
        catalyst_recent=True,
        breakout_volume_ratio=3.0,
    )

    assert result.passes is False
    assert result.points == 5.0


def test_supply_demand_strong_accumulation_passes() -> None:
    result = score_supply_demand(
        up_down_volume_ratio=1.35,
        volume_surge_ratio=1.6,
        shares_outstanding_millions=50.0,
    )

    assert result.passes is True
    assert result.points == 11.5
    assert result.metrics["strong_demand"] is True


def test_supply_demand_small_share_supply_cannot_rescue_weak_demand() -> None:
    result = score_supply_demand(
        up_down_volume_ratio=0.9,
        volume_surge_ratio=1.1,
        shares_outstanding_millions=10.0,
    )

    assert result.passes is False
    assert result.points == 2.0


def test_leader_is_anchored_to_rs_with_group_confirmation() -> None:
    result = score_leader(rs_rating=91.0, group_rank=15)

    assert result.passes is True
    assert result.points == 20.0
    assert result.metrics["group_points"] == 2.0


def test_leading_group_cannot_rescue_lagging_stock_rs() -> None:
    result = score_leader(rs_rating=74.0, group_rank=1)

    assert result.passes is False
    assert result.points == 12.0


def test_institutional_sponsorship_rewards_increasing_ownership() -> None:
    result = score_institutional_sponsorship(
        institutional_ownership_pct=62.0,
        ownership_change_pct=5.5,
        institutional_transactions_pct=2.0,
    )

    assert result.passes is True
    assert result.points == 14.0
    assert result.metrics["increasing_sponsorship"] is True


def test_institutional_high_ownership_is_not_penalized_by_legacy_sweet_spot() -> None:
    result = score_institutional_sponsorship(
        institutional_ownership_pct=88.0,
        ownership_change_pct=1.0,
    )

    assert result.passes is True
    assert result.points == 11.0


def test_institutional_static_sponsorship_does_not_pass_trend_gate() -> None:
    result = score_institutional_sponsorship(
        institutional_ownership_pct=70.0,
        ownership_change_pct=0.0,
        institutional_transactions_pct=-1.0,
    )

    assert result.passes is False
    assert result.points == 9.0


@pytest.mark.parametrize(
    ("score", "passes", "stance", "action"),
    [
        (90.0, True, "Power Trend", "aggressive"),
        (70.0, True, "Confirmed Uptrend", "normal"),
        (55.0, True, "Uptrend Under Pressure", "reduced"),
        (45.0, False, "Downtrend/Caution", "watchlist_only"),
        (20.0, False, "Correction — In Cash", "cash"),
    ],
)
def test_market_gate_reuses_exposure_bands(
    score: float,
    passes: bool,
    stance: str,
    action: str,
) -> None:
    result = score_market_gate(exposure_score=score)

    assert result.points == 0.0
    assert result.max_points == 0.0
    assert result.passes is passes
    assert result.metrics["stance"] == stance
    assert result.metrics["action"] == action


def test_market_gate_missing_score_is_unavailable() -> None:
    result = score_market_gate(exposure_score=None)

    assert result.available is False
    assert result.passes is False
    assert result.points == 0.0


def test_contract_serialization_is_api_friendly() -> None:
    result = score_current_earnings(eps_yoy=25.0)
    payload = result.as_dict()

    assert payload["letter"] == "C"
    assert payload["methodology_version"] == METHODOLOGY_VERSION
    assert payload["max_points"] == 20.0
