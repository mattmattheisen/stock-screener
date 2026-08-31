"""Tests for strict same-snapshot CAN SLIM V2 shadow batch evaluation."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from app.scanners.base_screener import StockData
from app.services.canslim_v2_shadow_batch_service import (
    CANSLIMV2ShadowBatchEvaluator,
    CANSLIMV2ShadowContext,
)


class _FakeEvaluator:
    def __init__(self) -> None:
        self.calls = []

    def evaluate_and_persist(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            created=len(self.calls) == 1,
            persistence_id=len(self.calls),
            record=SimpleNamespace(symbol=kwargs["symbol"]),
        )


def _stock_data(symbol: str) -> StockData:
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
        symbol=symbol,
        price_data=prices,
        benchmark_data=prices.copy(),
    )


def _context(score: float = 72.0) -> CANSLIMV2ShadowContext:
    return CANSLIMV2ShadowContext(
        market_exposure_score=score,
        group_rank=18,
        catalyst_recent=True,
    )


def test_batch_runs_only_after_complete_prefetch_validation() -> None:
    evaluator = _FakeEvaluator()
    batch = CANSLIMV2ShadowBatchEvaluator(evaluator)
    nvda = _stock_data("NVDA")
    msft = _stock_data("MSFT")

    result = batch.evaluate_and_persist_batch(
        symbols=["nvda", "MSFT"],
        data_by_symbol={"NVDA": nvda, "msft": msft},
        context_by_symbol={"nvda": _context(72.0), "MSFT": _context(68.0)},
        as_of_date=date(2026, 8, 31),
        run_ref=" feature-run:123 ",
    )

    assert result.run_ref == "feature-run:123"
    assert result.requested == 2
    assert result.created == 1
    assert result.reused == 1
    assert [call["symbol"] for call in evaluator.calls] == ["NVDA", "MSFT"]
    assert evaluator.calls[0]["data"] is nvda
    assert evaluator.calls[1]["data"] is msft
    assert evaluator.calls[0]["market_exposure_score"] == 72.0
    assert evaluator.calls[1]["market_exposure_score"] == 68.0


def test_batch_rejects_missing_prefetch_before_any_evaluation() -> None:
    evaluator = _FakeEvaluator()
    batch = CANSLIMV2ShadowBatchEvaluator(evaluator)

    with pytest.raises(ValueError, match="complete prefetch"):
        batch.evaluate_and_persist_batch(
            symbols=["NVDA", "MSFT"],
            data_by_symbol={"NVDA": _stock_data("NVDA")},
            context_by_symbol={"NVDA": _context(), "MSFT": _context()},
            as_of_date=date(2026, 8, 31),
            run_ref="feature-run:123",
        )

    assert evaluator.calls == []


def test_batch_rejects_missing_context_before_any_evaluation() -> None:
    evaluator = _FakeEvaluator()
    batch = CANSLIMV2ShadowBatchEvaluator(evaluator)

    with pytest.raises(ValueError, match="complete point-in-time context"):
        batch.evaluate_and_persist_batch(
            symbols=["NVDA", "MSFT"],
            data_by_symbol={
                "NVDA": _stock_data("NVDA"),
                "MSFT": _stock_data("MSFT"),
            },
            context_by_symbol={"NVDA": _context()},
            as_of_date=date(2026, 8, 31),
            run_ref="feature-run:123",
        )

    assert evaluator.calls == []


def test_batch_rejects_duplicate_symbols_after_normalization() -> None:
    evaluator = _FakeEvaluator()
    batch = CANSLIMV2ShadowBatchEvaluator(evaluator)

    with pytest.raises(ValueError, match="duplicate shadow batch symbol"):
        batch.evaluate_and_persist_batch(
            symbols=["nvda", "NVDA"],
            data_by_symbol={"NVDA": _stock_data("NVDA")},
            context_by_symbol={"NVDA": _context()},
            as_of_date=date(2026, 8, 31),
            run_ref="feature-run:123",
        )

    assert evaluator.calls == []


def test_batch_rejects_stock_data_identity_mismatch_before_any_evaluation() -> None:
    evaluator = _FakeEvaluator()
    batch = CANSLIMV2ShadowBatchEvaluator(evaluator)

    with pytest.raises(ValueError, match="data identity mismatch"):
        batch.evaluate_and_persist_batch(
            symbols=["NVDA"],
            data_by_symbol={"NVDA": _stock_data("MSFT")},
            context_by_symbol={"NVDA": _context()},
            as_of_date=date(2026, 8, 31),
            run_ref="feature-run:123",
        )

    assert evaluator.calls == []
