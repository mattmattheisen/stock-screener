"""Tests for explicit same-snapshot CAN SLIM V1-vs-V2 shadow evaluation."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from app.scanners.base_screener import ScreenerResult, StockData
from app.services.canslim_v2_shadow_service import CANSLIMV2ShadowEvaluator


class _FakeV1Scanner:
    def __init__(self) -> None:
        self.seen_data = None

    def scan_stock(self, symbol, data, criteria=None):
        self.seen_data = data
        return ScreenerResult(
            score=76.0,
            passes=True,
            rating="Buy",
            breakdown={},
            details={},
            screener_name="canslim",
        )


class _FakeV2Scanner:
    def __init__(self) -> None:
        self.seen_data = None
        self.seen_criteria = None

    def scan_stock(self, symbol, data, criteria=None):
        self.seen_data = data
        self.seen_criteria = criteria
        criteria_payload = {
            letter: {
                "letter": letter,
                "points": 10.0 if letter != "M" else 0.0,
                "max_points": 20.0 if letter != "M" else 0.0,
                "passes": True,
                "available": True,
                "metrics": {},
                "reason": "test",
            }
            for letter in "CANSLIM"
        }
        criteria_payload["M"]["metrics"] = {
            "exposure_score": 72.0,
            "stance": "Confirmed Uptrend",
        }
        return ScreenerResult(
            score=84.0,
            passes=True,
            rating="Buy",
            breakdown={},
            details={
                "methodology_version": "canslim_v2",
                "status": "qualified",
                "stock_passes": True,
                "market_passes": True,
                "actionable": True,
                "market": criteria_payload["M"],
                "full_analysis": {"criteria": criteria_payload},
            },
            screener_name="canslim_v2",
        )


class _FakeRepository:
    def __init__(self) -> None:
        self.saved = None

    def save(self, evidence):
        self.saved = evidence
        return SimpleNamespace(id=42), True


def _stock_data() -> StockData:
    prices = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1_000_000],
        },
        index=pd.to_datetime(["2026-08-31"]),
    )
    return StockData(
        symbol="NVDA",
        price_data=prices,
        benchmark_data=prices.copy(),
    )


def test_evaluator_runs_v1_and_v2_on_exact_same_stock_data_and_persists():
    v1 = _FakeV1Scanner()
    v2 = _FakeV2Scanner()
    repository = _FakeRepository()
    data = _stock_data()
    evaluator = CANSLIMV2ShadowEvaluator(
        repository,
        v1_scanner=v1,
        v2_scanner=v2,
    )

    result = evaluator.evaluate_and_persist(
        symbol="nvda",
        data=data,
        as_of_date=date(2026, 8, 31),
        run_ref="feature-run:123",
        market_exposure_score=72.0,
        group_rank=18,
        catalyst_recent=True,
    )

    assert v1.seen_data is data
    assert v2.seen_data is data
    assert v2.seen_criteria == {
        "market_exposure_score": 72.0,
        "group_rank": 18,
        "catalyst_recent": True,
    }
    assert result.persistence_id == 42
    assert result.created is True
    assert result.record.symbol == "NVDA"
    assert result.record.as_of_date == "2026-08-31"
    assert result.record.run_ref == "feature-run:123"
    assert repository.saved == result.record.as_dict()


def test_evaluator_requires_run_ref_before_scanning():
    v1 = _FakeV1Scanner()
    v2 = _FakeV2Scanner()
    evaluator = CANSLIMV2ShadowEvaluator(
        _FakeRepository(),
        v1_scanner=v1,
        v2_scanner=v2,
    )

    try:
        evaluator.evaluate_and_persist(
            symbol="NVDA",
            data=_stock_data(),
            as_of_date=date(2026, 8, 31),
            run_ref=" ",
            market_exposure_score=72.0,
        )
    except ValueError as exc:
        assert "run_ref" in str(exc)
    else:
        raise AssertionError("expected missing run_ref to be rejected")

    assert v1.seen_data is None
    assert v2.seen_data is None
