from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.schemas.validation import ValidationSourceKind
from app.services.validation_service import (
    PriceOutcomeCalculator,
    RawValidationEvent,
    ValidationService,
)


class _FakePriceCache:
    def __init__(self, history: pd.DataFrame):
        self._history = history

    def get_many_cached_only(self, symbols, period="2y"):
        return {symbol: self._history for symbol in symbols}


def _event() -> RawValidationEvent:
    return RawValidationEvent(
        symbol="NVDA",
        source_kind=ValidationSourceKind.SCAN_PICK,
        source_ref="run:20-session-test",
        event_at=date(2026, 4, 1),
        attributes={"symbol": "NVDA"},
    )


def _history(session_count: int) -> pd.DataFrame:
    index = pd.bdate_range("2026-04-02", periods=session_count)
    rows = []
    for session_number in range(1, session_count + 1):
        rows.append(
            (
                100.0,
                100.0 + session_number,
                100.0 - (session_number / 2.0),
                100.0 + session_number,
            )
        )
    return pd.DataFrame(rows, index=index, columns=["Open", "High", "Low", "Close"])


def test_price_outcome_calculator_computes_only_mature_twenty_session_window():
    calculator = PriceOutcomeCalculator(_FakePriceCache(_history(20)))

    evaluated, degraded = calculator.evaluate_many([_event()])

    assert degraded == []
    result = evaluated[0]
    assert result.entry_at == date(2026, 4, 2)
    assert result.return_5s_pct == pytest.approx(5.0)
    assert result.return_20s_pct == pytest.approx(20.0)
    assert result.mfe_20s_pct == pytest.approx(20.0)
    assert result.mae_20s_pct == pytest.approx(-10.0)
    assert result.missing_horizons == frozenset()

    response = result.to_response()
    assert response.return_20s_pct == pytest.approx(20.0)
    assert response.mfe_20s_pct == pytest.approx(20.0)
    assert response.mae_20s_pct == pytest.approx(-10.0)


def test_price_outcome_calculator_keeps_five_session_result_when_twenty_is_immature():
    calculator = PriceOutcomeCalculator(_FakePriceCache(_history(19)))

    evaluated, degraded = calculator.evaluate_many([_event()])

    assert degraded == []
    result = evaluated[0]
    assert result.return_5s_pct == pytest.approx(5.0)
    assert result.return_20s_pct is None
    assert result.mfe_20s_pct is None
    assert result.mae_20s_pct is None
    assert result.missing_horizons == frozenset({20})


def test_validation_service_reports_one_five_and_twenty_session_summaries():
    mature_calculator = PriceOutcomeCalculator(_FakePriceCache(_history(20)))
    immature_calculator = PriceOutcomeCalculator(_FakePriceCache(_history(19)))
    mature = mature_calculator.evaluate_many([_event()])[0][0]
    immature = immature_calculator.evaluate_many([_event()])[0][0]

    service = object.__new__(ValidationService)
    summaries = service._build_horizon_summaries([mature, immature])

    assert [summary.horizon_sessions for summary in summaries] == [1, 5, 20]

    five_session = summaries[1]
    assert five_session.sample_size == 2
    assert five_session.skipped_missing_history == 0

    twenty_session = summaries[2]
    assert twenty_session.sample_size == 1
    assert twenty_session.positive_rate == pytest.approx(1.0)
    assert twenty_session.avg_return_pct == pytest.approx(20.0)
    assert twenty_session.median_return_pct == pytest.approx(20.0)
    assert twenty_session.avg_mfe_pct == pytest.approx(20.0)
    assert twenty_session.avg_mae_pct == pytest.approx(-10.0)
    assert twenty_session.skipped_missing_history == 1
