from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from types import SimpleNamespace
from types import MappingProxyType

import pytest

from app.domain.relative_strength import BALANCED_RS_FORMULA_VERSION
from app.models.market_breadth import MarketBreadth
from app.models.stock_universe import StockUniverse
from app.scripts import export_static_site
from app.services.market_exposure_service import EXPOSURE_BACKFILL_DAYS
from app.services.static_market_publish_policy import StaticMarketRsArtifactState
from app.services.static_breadth_eligibility import StaticBreadthEligibility


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _ReadyGroupRankBackfill:
    ready_for_enrichment = True

    def as_dict(self) -> dict[str, str]:
        return {"status": "completed"}


def _patch_breadth_eligibility(
    monkeypatch,
    eligible_counts_by_date,
    *,
    candidate_counts_by_date=None,
    policy="point_in_time",
):
    eligible_counts = dict(eligible_counts_by_date)
    candidate_counts = dict(candidate_counts_by_date or eligible_counts)

    def classify(_db, *, market, calculation_dates):
        del market
        eligible_symbols = {
            calculation_date: tuple(
                f"ELIGIBLE-{index}"
                for index in range(eligible_counts.get(calculation_date, 0))
            )
            for calculation_date in calculation_dates
        }
        return StaticBreadthEligibility(
            eligible_symbols_by_date=MappingProxyType(eligible_symbols),
            candidate_counts_by_date=MappingProxyType(
                {
                    calculation_date: candidate_counts.get(calculation_date, 0)
                    for calculation_date in calculation_dates
                }
            ),
            eligible_counts_by_date=MappingProxyType(
                {
                    calculation_date: eligible_counts.get(calculation_date, 0)
                    for calculation_date in calculation_dates
                }
            ),
            universe_policy_by_date=MappingProxyType(
                {calculation_date: policy for calculation_date in calculation_dates}
            ),
            eligibility_signatures_by_date=MappingProxyType(
                {
                    calculation_date: _breadth_signature(calculation_date)
                    for calculation_date in calculation_dates
                }
            ),
            unsupported_count=0,
            insufficient_history_count=0,
            exact_date_gap_count=0,
            unsupported_symbols=(),
            insufficient_history_symbols=(),
            exact_date_gap_symbols=(),
        )

    monkeypatch.setattr(
        export_static_site,
        "classify_static_breadth_eligibility",
        classify,
    )


def _breadth_signature(calculation_date):
    return f"signature-{calculation_date.isoformat()}"


def test_refresh_static_daily_prices_uses_exposure_lookback_for_history_hydration(
    monkeypatch,
):
    init_kwargs: dict[str, object] = {}
    refresh_kwargs: dict[str, object] = {}

    class _FakeStaticDailyPriceRefreshService:
        def __init__(self, **kwargs):
            init_kwargs.update(kwargs)

        def refresh(self, **kwargs):
            refresh_kwargs.update(kwargs)
            return {"status": "completed"}

    monkeypatch.setattr(
        export_static_site,
        "StaticDailyPriceRefreshService",
        _FakeStaticDailyPriceRefreshService,
    )
    monkeypatch.setattr(export_static_site, "SessionLocal", object())
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(export_static_site, "BulkDataFetcher", lambda: object())

    result = export_static_site._refresh_static_daily_prices(
        as_of_date=date(2026, 7, 31),
        market="US",
    )

    assert result == {"status": "completed"}
    assert (
        init_kwargs["breadth_history_price_lookback_days"]
        == EXPOSURE_BACKFILL_DAYS
    )
    assert refresh_kwargs == {
        "as_of_date": date(2026, 7, 31),
        "market": "US",
        "ensure_static_history": True,
    }


def test_static_daily_refresh_ensures_market_breadth_before_exposure(monkeypatch):
    events: list[tuple[str, str]] = []
    breadth_call: dict[str, object] = {}

    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("HK",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 7, 31),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )
    monkeypatch.setattr(
        export_static_site,
        "_prepare_static_rs_formula",
        lambda *, market, as_of_date, formula_version: {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "classify_static_market_rs_artifact_result",
        lambda *args, **kwargs: StaticMarketRsArtifactState.READY,
    )

    def ensure_breadth(*, as_of_date, market, min_trading_days=None, lookback_days=None):
        breadth_call.update(
            as_of_date=as_of_date,
            market=market,
            min_trading_days=min_trading_days,
            lookback_days=lookback_days,
        )
        events.append(("breadth", market))
        return {"status": "completed", "market": market, "as_of_date": as_of_date.isoformat()}

    def compute_exposure(*, as_of_date, market):
        events.append(("exposure", market))
        return {"market": market, "date": as_of_date.isoformat(), "status": "stored"}

    monkeypatch.setattr(export_static_site, "_ensure_breadth_history", ensure_breadth)
    monkeypatch.setattr(export_static_site, "_compute_static_market_exposure", compute_exposure)

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(
            run=lambda **kwargs: {
                "status": "published",
                "run_id": 7,
                "market": kwargs["market"],
            }
        ),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_group_rank_history",
        lambda **kwargs: _ReadyGroupRankBackfill(),
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="HK",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert warnings == []
    assert results["market_exposure"]["HK"]["status"] == "stored"
    assert events.index(("breadth", "HK")) < events.index(("exposure", "HK"))
    assert breadth_call == {
        "as_of_date": date(2026, 7, 31),
        "market": "HK",
        "min_trading_days": 0,
        "lookback_days": EXPOSURE_BACKFILL_DAYS,
    }


def test_static_daily_refresh_rewinds_to_latest_benchmark_backed_session(
    monkeypatch,
):
    prepare_calls: list[date] = []
    snapshot_calls: list[dict[str, object]] = []

    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("DE",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 8, 3),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )

    def prepare_static_rs(*, market, as_of_date, formula_version):
        prepare_calls.append(as_of_date)
        if as_of_date == date(2026, 8, 3):
            return {
                "status": "failed",
                "market": market,
                "as_of_date": "2026-08-03",
                "formula_version": formula_version,
                "reason_code": "benchmark_adjusted_anchor_missing",
                "diagnostics": {
                    "error": "benchmark_not_current",
                    "market": market,
                    "date": "2026-08-03",
                    "benchmark_candidates": [
                        {
                            "symbol": "^GDAXI",
                            "role": "primary",
                            "source": "fetch",
                            "status": "stale_required_date",
                            "latest_date": datetime(2026, 7, 31, 15, 30),
                        },
                    ],
                },
                "market_rs_run_id": None,
            }
        return {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        }

    monkeypatch.setattr(export_static_site, "_prepare_static_rs_formula", prepare_static_rs)
    monkeypatch.setattr(
        export_static_site,
        "_ensure_breadth_history",
        lambda **kwargs: {
            "status": "completed",
            "market": kwargs["market"],
            "as_of_date": kwargs["as_of_date"].isoformat(),
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "_compute_static_market_exposure",
        lambda **kwargs: {
            "market": kwargs["market"],
            "date": kwargs["as_of_date"].isoformat(),
            "status": "stored",
        },
    )

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    def build_snapshot(**kwargs):
        snapshot_calls.append(kwargs)
        return {
            "status": "published",
            "run_id": 7,
            "market": kwargs["market"],
            "as_of_date": kwargs["as_of_date_str"],
        }

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(run=build_snapshot),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_group_rank_history",
        lambda **kwargs: _ReadyGroupRankBackfill(),
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="DE",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert prepare_calls == [date(2026, 8, 3), date(2026, 7, 31)]
    assert results["market_rs"]["DE"]["status"] == "completed"
    assert results["market_rs"]["DE"]["as_of_date"] == "2026-07-31"
    assert snapshot_calls[0]["as_of_date_str"] == "2026-07-31"
    assert (
        "Static export market DE using benchmark-backed as-of date 2026-07-31 "
        "because benchmarks were unavailable for 2026-08-03."
    ) in warnings


def test_static_daily_refresh_skips_exposure_when_breadth_history_errors(monkeypatch):
    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("HK",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 7, 31),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )
    monkeypatch.setattr(
        export_static_site,
        "_prepare_static_rs_formula",
        lambda *, market, as_of_date, formula_version: {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "classify_static_market_rs_artifact_result",
        lambda *args, **kwargs: StaticMarketRsArtifactState.READY,
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_breadth_history",
        lambda **kwargs: {
            "status": "errored",
            "market": kwargs["market"],
            "as_of_date": kwargs["as_of_date"].isoformat(),
            "errors": 1,
            "error_dates": [kwargs["as_of_date"].isoformat()],
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "_compute_static_market_exposure",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("exposure must not compute when breadth is incomplete")
        ),
    )

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(
            run=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("snapshot must not publish after exposure is skipped")
            )
        ),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="HK",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert results["market_exposure"]["HK"]["error"] == "market_breadth_not_ready"
    assert results["feature_snapshots"]["HK"]["reason"] == "market_exposure_not_ready"
    assert (
        "Static export market HK exposure not stored for 2026-07-31: "
        "market_breadth_not_ready."
    ) in warnings


def test_static_daily_refresh_quarantines_breadth_history_exceptions(monkeypatch):
    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("HK",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 7, 31),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )
    monkeypatch.setattr(
        export_static_site,
        "_prepare_static_rs_formula",
        lambda *, market, as_of_date, formula_version: {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "classify_static_market_rs_artifact_result",
        lambda *args, **kwargs: StaticMarketRsArtifactState.READY,
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_breadth_history",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("cache read failed")),
    )
    monkeypatch.setattr(
        export_static_site,
        "_compute_static_market_exposure",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("exposure must not compute when breadth raises")
        ),
    )

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(
            run=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("snapshot must not publish after breadth raises")
            )
        ),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="HK",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert results["breadth_history"]["HK"] == {
        "status": "errored",
        "market": "HK",
        "as_of_date": "2026-07-31",
        "error": "cache read failed",
        "exception_type": "RuntimeError",
    }
    assert results["market_exposure"]["HK"]["error"] == "market_breadth_not_ready"
    assert results["feature_snapshots"]["HK"]["reason"] == "market_exposure_not_ready"
    assert (
        "Static export market HK breadth history failed for 2026-07-31: "
        "cache read failed"
    ) in warnings


def test_ensure_breadth_history_marks_backfill_errors_not_completed(monkeypatch):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(monkeypatch, {as_of_date: 1})
    backfill_kwargs: dict[str, object] = {}

    class _FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class _FakeDb(_FakeSession):
        def query(self, *args, **kwargs):
            return _FakeQuery()

    class _FakeBreadthCalculator:
        def __init__(self, db, price_cache, *, market):
            self.market = market

        def backfill_range(self, **kwargs):
            backfill_kwargs.update(kwargs)
            return {
                "total_dates": 1,
                "processed": 0,
                "errors": 1,
                "error_dates": [as_of_date.isoformat()],
            }

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        _FakeBreadthCalculator,
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="HK",
        min_trading_days=0,
    )

    assert result["status"] == "errored"
    assert result["errors"] == 1
    assert result["error_dates"] == ["2026-07-31"]
    assert result["hard_error_dates"] == ["2026-07-31"]
    assert result["unclassified_error_count"] == 0
    assert "tolerated_error_dates" not in result
    assert result["error"] == (
        "Cache-only breadth backfill has hard date errors "
        "(dates=2026-07-31)"
    )
    assert backfill_kwargs["exclude_unsupported_price_symbols"] is True
    assert backfill_kwargs["required_as_of_date"] == as_of_date


def test_ensure_breadth_history_recomputes_incomplete_existing_rows(monkeypatch):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(monkeypatch, {as_of_date: 2})
    backfill_kwargs: dict[str, object] = {}
    query_counts = {"market_breadth": 0}

    class _FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _FakeDb(_FakeSession):
        def query(self, entity, *args):
            if entity is MarketBreadth:
                query_counts["market_breadth"] += 1
                return _FakeQuery([
                    SimpleNamespace(date=as_of_date, total_stocks_scanned=1)
                ])
            if entity is StockUniverse.symbol:
                return _FakeQuery([("AAA",), ("BBB",)])
            return _FakeQuery([])

    class _FakeBreadthCalculator:
        def __init__(self, db, price_cache, *, market):
            self.market = market

        def backfill_range(self, **kwargs):
            backfill_kwargs.update(kwargs)
            return {
                "total_dates": 1,
                "processed": 1,
                "errors": 0,
                "error_dates": [],
                "target_symbols": 2,
                "symbols_with_cached_history": 2,
                "cache_miss_stocks": 0,
                "error_stocks": 0,
                "cache_coverage_ratio": 1.0,
                "scanned_stocks_by_date": {as_of_date.isoformat(): 2},
            }

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(export_static_site, "BreadthCalculatorService", _FakeBreadthCalculator)

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="HK",
        min_trading_days=0,
    )

    assert result["status"] == "completed"
    assert result["incomplete_existing_dates"] == 1
    assert result["recomputed_dates"] == 1
    assert backfill_kwargs["trading_dates"] == [as_of_date]
    assert len(backfill_kwargs["eligible_symbols_by_date"][as_of_date]) == 2
    assert query_counts["market_breadth"] == 1


def test_ensure_breadth_history_recomputes_ratio_window_after_historical_repair(
    monkeypatch,
):
    target_dates = [
        date(2026, 7, 16),
        date(2026, 7, 17),
        date(2026, 7, 20),
        date(2026, 7, 21),
        date(2026, 7, 22),
        date(2026, 7, 23),
        date(2026, 7, 24),
        date(2026, 7, 27),
        date(2026, 7, 28),
        date(2026, 7, 29),
        date(2026, 7, 30),
        date(2026, 7, 31),
    ]
    repair_date = target_dates[1]
    as_of_date = target_dates[-1]
    _patch_breadth_eligibility(
        monkeypatch, {calculation_date: 1 for calculation_date in target_dates}
    )
    backfill_kwargs: dict[str, object] = {}

    class _FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _FakeDb(_FakeSession):
        def query(self, entity, *args):
            if entity is MarketBreadth:
                return _FakeQuery([
                    SimpleNamespace(
                        date=calc_date,
                        total_stocks_scanned=1,
                        eligibility_signature=_breadth_signature(calc_date),
                    )
                    for calc_date in target_dates
                    if calc_date != repair_date
                ])
            if entity is StockUniverse.symbol:
                return _FakeQuery([("AAA",)])
            return _FakeQuery([])

    class _FakeBreadthCalculator:
        def __init__(self, db, price_cache, *, market):
            self.market = market

        def backfill_range(self, **kwargs):
            backfill_kwargs.update(kwargs)
            return {
                "total_dates": len(kwargs["trading_dates"]),
                "processed": len(kwargs["trading_dates"]),
                "errors": 0,
                "error_dates": [],
                "target_symbols": 1,
                "symbols_with_cached_history": 1,
                "cache_miss_stocks": 0,
                "error_stocks": 0,
                "cache_coverage_ratio": 1.0,
                "scanned_stocks_by_date": {
                    calculation_date.isoformat(): 1
                    for calculation_date in kwargs["trading_dates"]
                },
            }

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: target_dates,
    )
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        _FakeBreadthCalculator,
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="HK",
        min_trading_days=0,
    )

    assert result["status"] == "completed"
    assert result["recomputed_dates"] == 11
    assert backfill_kwargs["trading_dates"] == target_dates[1:]


def test_ensure_breadth_history_skips_validated_existing_rows(monkeypatch):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(monkeypatch, {as_of_date: 2})

    class _FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _FakeDb(_FakeSession):
        def query(self, entity, *args):
            if entity is MarketBreadth:
                return _FakeQuery([
                    SimpleNamespace(
                        date=as_of_date,
                        total_stocks_scanned=2,
                        eligibility_signature=_breadth_signature(as_of_date),
                    )
                ])
            if entity is StockUniverse.symbol:
                return _FakeQuery([("AAA",), ("BBB",)])
            return _FakeQuery([])

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("validated existing breadth should not recompute")
        ),
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="HK",
        min_trading_days=0,
    )

    assert result["status"] == "skipped"
    assert result["validated_existing_dates"] == 1
    assert result["eligible_stocks_by_date"] == {"2026-07-31": 2}


@pytest.mark.parametrize("market", ["US", "DE", "HK"])
def test_historical_breadth_reuses_rows_eligible_for_their_date(monkeypatch, market):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(
        monkeypatch,
        {as_of_date: 7},
        candidate_counts_by_date={as_of_date: 10},
    )

    class _FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    date=as_of_date,
                    total_stocks_scanned=7,
                    eligibility_signature=_breadth_signature(as_of_date),
                )
            ]

    class _FakeDb(_FakeSession):
        def query(self, *args, **kwargs):
            return _FakeQuery()

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("date-eligible existing breadth must be reused")
        ),
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market=market,
        min_trading_days=0,
    )

    assert result["status"] == "skipped"
    assert result["candidate_stocks_by_date"] == {"2026-07-31": 10}
    assert result["eligible_stocks_by_date"] == {"2026-07-31": 7}


def test_legacy_breadth_row_with_larger_count_recomputes_without_matching_signature(
    monkeypatch,
):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(
        monkeypatch,
        {as_of_date: 7},
        candidate_counts_by_date={as_of_date: 10},
    )
    calls = []

    class _FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    date=as_of_date,
                    total_stocks_scanned=10,
                    eligibility_signature=None,
                )
            ]

    class _FakeDb(_FakeSession):
        def query(self, *args, **kwargs):
            return _FakeQuery()

    class _FakeBreadthCalculator:
        def __init__(self, *args, **kwargs):
            pass

        def backfill_range(self, **kwargs):
            calls.append(kwargs)
            return {
                "total_dates": 1,
                "processed": 1,
                "errors": 0,
                "error_dates": [],
                "error_stocks": 0,
                "scanned_stocks_by_date": {as_of_date.isoformat(): 7},
            }

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(
        export_static_site, "BreadthCalculatorService", _FakeBreadthCalculator
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="US",
        min_trading_days=0,
    )

    assert result["status"] == "completed"
    assert result["incomplete_existing_dates"] == 1
    assert len(calls) == 1
    assert calls[0]["eligibility_signatures_by_date"] == {
        as_of_date: _breadth_signature(as_of_date)
    }


def test_ensure_breadth_history_skips_existing_rows_with_tolerated_historical_gaps(
    monkeypatch,
):
    previous_date = date(2026, 7, 30)
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(
        monkeypatch,
        {previous_date: 9, as_of_date: 10},
    )

    class _FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _FakeDb(_FakeSession):
        def query(self, entity, *args):
            if entity is MarketBreadth:
                return _FakeQuery([
                    SimpleNamespace(
                        date=previous_date,
                        total_stocks_scanned=9,
                        eligibility_signature=_breadth_signature(previous_date),
                    ),
                    SimpleNamespace(
                        date=as_of_date,
                        total_stocks_scanned=10,
                        eligibility_signature=_breadth_signature(as_of_date),
                    ),
                ])
            if entity is StockUniverse.symbol:
                return _FakeQuery([
                    (f"AAA{i}",)
                    for i in range(10)
                ])
            return _FakeQuery([])

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [previous_date, as_of_date],
    )
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("accepted historical coverage should not recompute")
        ),
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="HK",
        min_trading_days=0,
    )

    assert result["status"] == "skipped"
    assert result["validated_existing_dates"] == 2
    assert result["eligible_stocks_by_date"] == {
        "2026-07-30": 9,
        "2026-07-31": 10,
    }


def test_ensure_breadth_history_marks_calculation_errors_not_completed(monkeypatch):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(monkeypatch, {as_of_date: 2})

    class _FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class _FakeDb(_FakeSession):
        def query(self, *args, **kwargs):
            return _FakeQuery()

    class _FakeBreadthCalculator:
        def __init__(self, db, price_cache, *, market):
            self.market = market

        def backfill_range(self, **kwargs):
            return {
                "total_dates": 1,
                "processed": 1,
                "errors": 0,
                "error_dates": [],
                "target_symbols": 2,
                "symbols_with_cached_history": 2,
                "cache_miss_stocks": 0,
                "error_stocks": 1,
                "cache_coverage_ratio": 1.0,
            }

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        _FakeBreadthCalculator,
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="HK",
        min_trading_days=0,
    )

    assert result["status"] == "errored"
    assert result["error_stocks"] == 1
    assert result["error"] == (
        "Cache-only breadth backfill has calculation errors "
        "(error_stocks=1)"
    )


def test_ensure_breadth_history_marks_undercovered_backfill_rows_not_completed(
    monkeypatch,
):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(
        monkeypatch,
        {as_of_date: 8},
        candidate_counts_by_date={as_of_date: 10},
    )
    breadth_rows: list[SimpleNamespace] = []

    class _FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _FakeDb(_FakeSession):
        def query(self, entity, *args):
            if entity is MarketBreadth:
                return _FakeQuery(breadth_rows)
            if entity is StockUniverse.symbol:
                return _FakeQuery([(f"AAA{i}",) for i in range(10)])
            return _FakeQuery([])

    class _FakeBreadthCalculator:
        def __init__(self, db, price_cache, *, market):
            self.market = market

        def backfill_range(self, **kwargs):
            breadth_rows.append(
                SimpleNamespace(
                    date=as_of_date,
                    total_stocks_scanned=1,
                )
            )
            return {
                "total_dates": 1,
                "processed": 1,
                "errors": 0,
                "error_dates": [],
                "target_symbols": 10,
                "symbols_with_cached_history": 10,
                "cache_miss_stocks": 0,
                "error_stocks": 0,
                "cache_coverage_ratio": 1.0,
                "insufficient_history_observations": 9,
                "scanned_stocks_by_date": {as_of_date.isoformat(): 1},
            }

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        _FakeBreadthCalculator,
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="HK",
        min_trading_days=0,
    )

    assert result["status"] == "errored"
    assert result["undercovered_dates"] == ["2026-07-31"]
    assert result["eligible_stocks_by_date"] == {"2026-07-31": 8}
    assert result["scanned_stocks_by_date"] == {"2026-07-31": 1}
    assert result["error"] == (
        "Cache-only breadth backfill has insufficient usable coverage "
        "(scanned/eligible=2026-07-31:1/8)"
    )


def test_ensure_breadth_history_accepts_smaller_historical_eligible_universe(
    monkeypatch,
):
    as_of_date = date(2026, 7, 31)
    _patch_breadth_eligibility(
        monkeypatch,
        {as_of_date: 7},
        candidate_counts_by_date={as_of_date: 10},
        policy="current_active_fallback_v1",
    )
    breadth_rows: list[SimpleNamespace] = []

    class _FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

    class _FakeDb(_FakeSession):
        def query(self, entity, *args):
            if entity is MarketBreadth:
                return _FakeQuery(breadth_rows)
            if entity is StockUniverse.symbol:
                return _FakeQuery([(f"AAA{i}",) for i in range(10)])
            return _FakeQuery([])

    class _FakeBreadthCalculator:
        def __init__(self, db, price_cache, *, market):
            self.market = market

        def backfill_range(self, **kwargs):
            breadth_rows.append(
                SimpleNamespace(
                    date=as_of_date,
                    total_stocks_scanned=7,
                )
            )
            return {
                "total_dates": 1,
                "processed": 1,
                "errors": 0,
                "error_dates": [],
                "target_symbols": 10,
                "symbols_with_cached_history": 7,
                "cache_miss_stocks": 3,
                "error_stocks": 0,
                "cache_coverage_ratio": 0.7,
                "insufficient_history_observations": 3,
                "scanned_stocks_by_date": {as_of_date.isoformat(): 7},
            }

    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(
        export_static_site,
        "_generate_trading_dates",
        lambda *args, **kwargs: [as_of_date],
    )
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(
        export_static_site,
        "BreadthCalculatorService",
        _FakeBreadthCalculator,
    )

    result = export_static_site._ensure_breadth_history(
        as_of_date=as_of_date,
        market="CA",
        min_trading_days=0,
    )

    assert result["status"] == "completed"
    assert result["candidate_stocks_by_date"] == {"2026-07-31": 10}
    assert result["eligible_stocks_by_date"] == {"2026-07-31": 7}
    assert result["scanned_stocks_by_date"] == {"2026-07-31": 7}
    assert result["universe_policy_by_date"] == {
        "2026-07-31": "current_active_fallback_v1"
    }
    assert "undercovered_dates" not in result
    assert "error" not in result
