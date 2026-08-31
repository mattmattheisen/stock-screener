"""Tests for point-in-time CAN SLIM V1/V2 shadow comparison records."""

import pytest

from app.scanners.base_screener import ScreenerResult
from app.scanners.canslim_v2_shadow import build_shadow_record
from app.scanners.criteria.canslim_v2 import (
    score_annual_earnings,
    score_current_earnings,
    score_institutional_sponsorship,
    score_leader,
    score_market_gate,
    score_new_highs,
    score_supply_demand,
)
from app.scanners.criteria.canslim_v2_scorecard import build_scorecard


def _v1(*, score: float = 76.0, passes: bool = True) -> ScreenerResult:
    return ScreenerResult(
        score=score,
        passes=passes,
        rating="Buy" if passes else "Watch",
        breakdown={},
        details={},
        screener_name="canslim",
    )


def _v2(*, market_score: float = 70.0) -> ScreenerResult:
    scorecard = build_scorecard(
        [
            score_current_earnings(
                eps_yoy=45.0,
                prior_eps_yoy=30.0,
                sales_yoy=30.0,
            ),
            score_annual_earnings(
                eps_cagr=32.0,
                years_available=5,
                eps_rating=90.0,
                roe=22.0,
            ),
            score_new_highs(
                distance_from_52w_high_pct=3.0,
                catalyst_recent=True,
                breakout_volume_ratio=1.8,
            ),
            score_supply_demand(
                up_down_volume_ratio=1.4,
                volume_surge_ratio=1.8,
                shares_outstanding_millions=60.0,
            ),
            score_leader(rs_rating=92.0, group_rank=20),
            score_institutional_sponsorship(
                institutional_ownership_pct=65.0,
                ownership_change_pct=3.0,
                institutional_transactions_pct=2.0,
            ),
            score_market_gate(exposure_score=market_score),
        ]
    )
    market = scorecard.criteria[next(letter for letter in scorecard.criteria if letter.value == "M")]
    details = {
        "methodology_version": scorecard.methodology_version,
        "status": scorecard.status,
        "stock_passes": scorecard.stock_passes,
        "market_passes": scorecard.market_passes,
        "actionable": scorecard.actionable,
        "market": market.as_dict(),
        "full_analysis": scorecard.as_dict(),
    }
    return ScreenerResult(
        score=scorecard.stock_score,
        passes=scorecard.actionable,
        rating="Buy" if scorecard.actionable else "Market Blocked",
        breakdown={},
        details=details,
        screener_name="canslim_v2",
    )


def test_shadow_record_preserves_same_run_evidence() -> None:
    record = build_shadow_record(
        symbol="nvda",
        v1_result=_v1(score=76.0),
        v2_result=_v2(market_score=72.0),
        as_of_date="2026-08-31",
        run_ref="run:123",
    )

    assert record.symbol == "NVDA"
    assert record.as_of_date == "2026-08-31"
    assert record.run_ref == "run:123"
    assert record.v1_score == 76.0
    assert record.v2_stock_score >= 70.0
    assert record.v2_actionable is True
    assert record.market_exposure_score == 72.0
    assert set(record.criteria) == set("CANSLIM")


def test_shadow_record_exposes_market_only_disagreement() -> None:
    record = build_shadow_record(
        symbol="TEST",
        v1_result=_v1(passes=True),
        v2_result=_v2(market_score=20.0),
    )

    assert record.v2_stock_passes is True
    assert record.v2_market_passes is False
    assert record.v2_actionable is False
    assert record.v2_status == "market_blocked"
    assert record.action_disagreement is True
    assert record.market_stance == "Correction — In Cash"


def test_shadow_record_is_json_friendly() -> None:
    payload = build_shadow_record(
        symbol="TEST",
        v1_result=_v1(),
        v2_result=_v2(),
    ).as_dict()

    assert payload["methodology_version"] == "canslim_v2"
    assert isinstance(payload["criteria"], dict)
    assert payload["criteria"]["M"]["max_points"] == 0.0


def test_shadow_record_rejects_wrong_scanner_or_incomplete_v2_evidence() -> None:
    wrong_v1 = _v1()
    wrong_v1.screener_name = "minervini"
    with pytest.raises(ValueError, match="legacy canslim"):
        build_shadow_record(symbol="TEST", v1_result=wrong_v1, v2_result=_v2())

    incomplete = ScreenerResult(
        score=80.0,
        passes=True,
        rating="Buy",
        breakdown={},
        details={},
        screener_name="canslim_v2",
    )
    with pytest.raises(ValueError, match="full_analysis"):
        build_shadow_record(symbol="TEST", v1_result=_v1(), v2_result=incomplete)
