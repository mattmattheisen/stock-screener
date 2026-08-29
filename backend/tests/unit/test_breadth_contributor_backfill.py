from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from app.database import Base
from app.models.market_breadth import MarketBreadth
from app.scripts.backfill_breadth_contributors import main
from app.services.breadth_contributor_backfill import (
    BreadthContributorBackfillService,
)
from app.services.derived_data_execution_policy import (
    DerivedDataExecutionMode,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[MarketBreadth.__table__])
    return sessionmaker(bind=engine)()


def _aggregate(market: str, calculation_date: date, *, revision: int = 3):
    return MarketBreadth(
        market=market,
        date=calculation_date,
        calculation_revision=revision,
        stocks_up_4pct=0,
        stocks_down_4pct=0,
        stocks_up_25pct_quarter=0,
        stocks_down_25pct_quarter=0,
        stocks_up_25pct_month=0,
        stocks_down_25pct_month=0,
        stocks_up_50pct_month=0,
        stocks_down_50pct_month=0,
        stocks_up_13pct_34days=0,
        stocks_down_13pct_34days=0,
        atr_10x_extension_count=0,
        total_stocks_scanned=0,
    )


def test_service_selects_latest_twenty_current_revision_dates():
    db = _db_session()
    first = date(2026, 7, 1)
    db.add_all(
        [_aggregate("US", first + timedelta(days=offset)) for offset in range(22)]
        + [_aggregate("US", first + timedelta(days=30), revision=2)]
        + [_aggregate("CA", first + timedelta(days=40))]
    )
    db.commit()
    executor = MagicMock()
    executor.execute.return_value.to_legacy_dict.return_value = {
        "total_dates": 20,
        "processed": 20,
        "errors": 0,
        "error_dates": [],
    }

    report = BreadthContributorBackfillService(
        db,
        calculator=MagicMock(market="US"),
        executor=executor,
    ).run(limit=20)

    call = executor.execute.call_args
    plan = call.args[0]
    assert plan.dates == tuple(
        first + timedelta(days=offset) for offset in range(2, 22)
    )
    assert call.kwargs["policy"].mode is DerivedDataExecutionMode.STRICT_CACHE_ONLY
    assert call.kwargs["require_complete_cache_coverage"] is True
    assert call.kwargs["contributor_only"] is True
    assert report == {
        "market": "US",
        "requested_dates": 20,
        "committed_dates": 20,
    }


def test_service_with_no_revision_three_aggregates_is_a_noop():
    db = _db_session()
    db.add(_aggregate("US", date(2026, 8, 1), revision=2))
    db.commit()
    executor = MagicMock()

    report = BreadthContributorBackfillService(
        db,
        calculator=MagicMock(market="US"),
        executor=executor,
    ).run(limit=20)

    assert report == {
        "market": "US",
        "requested_dates": 0,
        "committed_dates": 0,
    }
    executor.execute.assert_not_called()


def test_cli_runs_each_requested_market_and_reports_json(capsys):
    calls = []

    def run_market(market, limit):
        calls.append((market, limit))
        return {
            "market": market,
            "requested_dates": limit,
            "committed_dates": limit,
        }

    exit_code = main(
        ["--markets", "us,CA", "--limit", "5"],
        run_market=run_market,
    )

    assert exit_code == 0
    assert calls == [("US", 5), ("CA", 5)]
    output = capsys.readouterr().out
    assert '"market": "US"' in output
    assert '"market": "CA"' in output


def test_cli_rejects_an_explicit_empty_market_selection():
    with pytest.raises(SystemExit) as exc_info:
        main(["--markets", ", ,"])

    assert exc_info.value.code == 2


def test_cli_returns_nonzero_when_any_market_fails(capsys):
    def run_market(market, limit):
        if market == "CA":
            raise ValueError("CA,2026-08-28,stocks_up_4pct,2,1")
        return {
            "market": market,
            "requested_dates": limit,
            "committed_dates": limit,
        }

    exit_code = main(
        ["--markets", "US,CA", "--limit", "20"],
        run_market=run_market,
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "CA,2026-08-28,stocks_up_4pct,2,1" in output
