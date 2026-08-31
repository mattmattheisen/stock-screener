"""Tests for prospective-only CAN SLIM V2 shadow evidence collection."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from app.domain.relative_strength import BALANCED_RS_FORMULA_VERSION
from app.domain.scanning.ports import MarketRsResolution
from app.scanners.base_screener import StockData
from app.services.benchmark_resolution import benchmark_remote_fetch_allowed
from app.services.canslim_v2_prospective_shadow_service import (
    CANSLIMV2ProspectiveShadowCollector,
    MarketExposureSnapshot,
    ProspectiveShadowIntegrityError,
)


AS_OF = date(2026, 8, 31)


def _frame(end: str = "2026-08-31") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1_000_000],
        },
        index=pd.to_datetime([end]),
    )


def _stock_data(
    symbol: str,
    *,
    stock_end: str = "2026-08-31",
    benchmark_end: str = "2026-08-31",
    market: str = "US",
    fetch_errors: dict[str, str] | None = None,
) -> StockData:
    return StockData(
        symbol=symbol,
        price_data=_frame(stock_end),
        benchmark_data=_frame(benchmark_end),
        fundamentals={},
        quarterly_growth={},
        market=market,
        fetch_errors=fetch_errors or {},
    )


def _canonical_resolution(symbols=("AAPL", "MSFT")) -> MarketRsResolution:
    ratings = {
        symbol: {
            "rs_rating": 90,
            "rs_rating_1m": 85,
            "rs_rating_3m": 88,
            "rs_rating_12m": 92,
        }
        for symbol in symbols
    }
    return MarketRsResolution.canonical(
        market="US",
        as_of_date=AS_OF,
        formula_version=BALANCED_RS_FORMULA_VERSION,
        run_id=321,
        universe_size=1200,
        ratings_by_symbol=ratings,
    )


class _FakeProvider:
    def __init__(self, prepared, *, error: Exception | None = None):
        self.prepared = prepared
        self.error = error
        self.remote_fetch_allowed_during_prepare = None
        self.prepare_kwargs = None
        self.applied_resolution = None

    def prepare_data_bulk(self, symbols, requirements, **kwargs):
        self.remote_fetch_allowed_during_prepare = benchmark_remote_fetch_allowed()
        self.prepare_kwargs = {
            "symbols": tuple(symbols),
            "requirements": requirements,
            **kwargs,
        }
        if self.error is not None:
            raise self.error
        return self.prepared

    def apply_market_rs_resolution(self, results, resolution):
        self.applied_resolution = resolution
        for item in results.values():
            item.rs_source = resolution.stock_source(item.symbol)


class _FakeMarketRsReader:
    def __init__(self, resolution):
        self.resolution = resolution
        self.calls = []

    def get(self, **kwargs):
        self.calls.append(kwargs)
        return self.resolution


class _FakeExposureReader:
    def __init__(self, snapshot=None, *, error: Exception | None = None):
        self.snapshot = snapshot or MarketExposureSnapshot(
            market="US",
            as_of_date=AS_OF,
            exposure_score=72.0,
            stance="Confirmed Uptrend",
        )
        self.error = error
        self.calls = []

    def get_exact(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.snapshot


class _FakeBatchEvaluator:
    def __init__(self):
        self.calls = []

    def evaluate_and_persist_batch(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            run_ref=kwargs["run_ref"],
            as_of_date=kwargs["as_of_date"],
            results=(),
            requested=len(kwargs["symbols"]),
            created=0,
            reused=len(kwargs["symbols"]),
        )


def _collector(
    provider,
    *,
    resolution=None,
    exposure_reader=None,
    batch=None,
):
    rs_reader = _FakeMarketRsReader(resolution or _canonical_resolution())
    batch_evaluator = batch or _FakeBatchEvaluator()
    collector = CANSLIMV2ProspectiveShadowCollector(
        stock_data_provider=provider,
        market_rs_reader=rs_reader,
        market_exposure_reader=exposure_reader or _FakeExposureReader(),
        batch_evaluator=batch_evaluator,
    )
    return collector, rs_reader, batch_evaluator


def test_collect_uses_cache_only_preparation_exact_date_canonical_rs_and_context():
    provider = _FakeProvider(
        {
            "AAPL": _stock_data("AAPL"),
            "MSFT": _stock_data("MSFT"),
        }
    )
    collector, rs_reader, batch = _collector(provider)

    result = collector.collect(
        symbols=["aapl", "MSFT"],
        as_of_date=AS_OF,
        run_ref="prospective:2026-08-31:us-growth",
        market="us",
        group_rank_by_symbol={"AAPL": 12},
        catalyst_recent_by_symbol={"MSFT": True},
    )

    assert provider.remote_fetch_allowed_during_prepare is False
    assert benchmark_remote_fetch_allowed() is True
    assert provider.prepare_kwargs["symbols"] == ("AAPL", "MSFT")
    assert provider.prepare_kwargs["allow_partial"] is False
    assert provider.prepare_kwargs["batch_only_prices"] is True
    assert provider.prepare_kwargs["batch_only_fundamentals"] is True
    assert provider.prepare_kwargs["requirements"].needs_benchmark is True
    assert provider.prepare_kwargs["requirements"].needs_fundamentals is True

    assert rs_reader.calls == [
        {
            "market": "US",
            "symbols": ("AAPL", "MSFT"),
            "as_of_date": AS_OF,
        }
    ]
    assert provider.applied_resolution is rs_reader.resolution
    assert batch.calls[0]["symbols"] == ("AAPL", "MSFT")
    assert batch.calls[0]["context_by_symbol"]["AAPL"].market_exposure_score == 72.0
    assert batch.calls[0]["context_by_symbol"]["AAPL"].group_rank == 12
    assert batch.calls[0]["context_by_symbol"]["AAPL"].catalyst_recent is None
    assert batch.calls[0]["context_by_symbol"]["MSFT"].group_rank is None
    assert batch.calls[0]["context_by_symbol"]["MSFT"].catalyst_recent is True

    assert result.market == "US"
    assert result.market_exposure_score == 72.0
    assert result.market_stance == "Confirmed Uptrend"
    assert result.market_rs_formula_version == BALANCED_RS_FORMULA_VERSION
    assert result.market_rs_run_id == 321
    assert result.market_rs_universe_size == 1200


def test_benchmark_remote_fetch_guard_restores_after_preparation_error():
    provider = _FakeProvider({}, error=RuntimeError("cache exploded"))
    collector, _, batch = _collector(provider)

    assert benchmark_remote_fetch_allowed() is True
    with pytest.raises(RuntimeError, match="cache exploded"):
        collector.collect(
            symbols=["AAPL"],
            as_of_date=AS_OF,
            run_ref="run:1",
        )

    assert provider.remote_fetch_allowed_during_prepare is False
    assert benchmark_remote_fetch_allowed() is True
    assert batch.calls == []


def test_rejects_stock_snapshot_date_drift_before_market_rs_or_evaluation():
    provider = _FakeProvider({"AAPL": _stock_data("AAPL", stock_end="2026-08-28")})
    collector, rs_reader, batch = _collector(
        provider,
        resolution=_canonical_resolution(("AAPL",)),
    )

    with pytest.raises(ProspectiveShadowIntegrityError, match="stock snapshot ends"):
        collector.collect(symbols=["AAPL"], as_of_date=AS_OF, run_ref="run:1")

    assert rs_reader.calls == []
    assert batch.calls == []


def test_rejects_benchmark_snapshot_date_drift_before_market_rs_or_evaluation():
    provider = _FakeProvider(
        {"AAPL": _stock_data("AAPL", benchmark_end="2026-08-28")}
    )
    collector, rs_reader, batch = _collector(
        provider,
        resolution=_canonical_resolution(("AAPL",)),
    )

    with pytest.raises(ProspectiveShadowIntegrityError, match="benchmark snapshot ends"):
        collector.collect(symbols=["AAPL"], as_of_date=AS_OF, run_ref="run:1")

    assert rs_reader.calls == []
    assert batch.calls == []


def test_rejects_market_mismatch_before_market_rs_or_evaluation():
    provider = _FakeProvider({"AAPL": _stock_data("AAPL", market="JP")})
    collector, rs_reader, batch = _collector(
        provider,
        resolution=_canonical_resolution(("AAPL",)),
    )

    with pytest.raises(ProspectiveShadowIntegrityError, match="expected US"):
        collector.collect(symbols=["AAPL"], as_of_date=AS_OF, run_ref="run:1")

    assert rs_reader.calls == []
    assert batch.calls == []


def test_rejects_cache_only_preparation_that_omits_a_requested_symbol():
    provider = _FakeProvider({"AAPL": _stock_data("AAPL")})
    collector, rs_reader, batch = _collector(provider)

    with pytest.raises(ProspectiveShadowIntegrityError, match="omitted requested symbols"):
        collector.collect(
            symbols=["AAPL", "MSFT"],
            as_of_date=AS_OF,
            run_ref="run:1",
        )

    assert rs_reader.calls == []
    assert batch.calls == []


def test_rejects_fetch_errors_even_if_provider_returns_stock_data():
    provider = _FakeProvider(
        {"AAPL": _stock_data("AAPL", fetch_errors={"fundamentals": "missing"})}
    )
    collector, rs_reader, batch = _collector(
        provider,
        resolution=_canonical_resolution(("AAPL",)),
    )

    with pytest.raises(ProspectiveShadowIntegrityError, match="fetch errors"):
        collector.collect(symbols=["AAPL"], as_of_date=AS_OF, run_ref="run:1")

    assert rs_reader.calls == []
    assert batch.calls == []


def test_rejects_legacy_market_rs():
    provider = _FakeProvider({"AAPL": _stock_data("AAPL")})
    legacy = MarketRsResolution.legacy(market="US", as_of_date=AS_OF)
    collector, _, batch = _collector(provider, resolution=legacy)

    with pytest.raises(ProspectiveShadowIntegrityError, match="requires canonical Market RS"):
        collector.collect(symbols=["AAPL"], as_of_date=AS_OF, run_ref="run:1")

    assert provider.applied_resolution is None
    assert batch.calls == []


def test_rejects_canonical_market_rs_missing_requested_symbol():
    provider = _FakeProvider(
        {
            "AAPL": _stock_data("AAPL"),
            "MSFT": _stock_data("MSFT"),
        }
    )
    resolution = _canonical_resolution(("AAPL",))
    collector, _, batch = _collector(provider, resolution=resolution)

    with pytest.raises(ProspectiveShadowIntegrityError, match="missing requested symbols: MSFT"):
        collector.collect(
            symbols=["AAPL", "MSFT"],
            as_of_date=AS_OF,
            run_ref="run:1",
        )

    assert provider.applied_resolution is None
    assert batch.calls == []


def test_rejects_market_exposure_identity_drift_before_data_preparation():
    provider = _FakeProvider({"AAPL": _stock_data("AAPL")})
    exposure_reader = _FakeExposureReader(
        MarketExposureSnapshot(
            market="US",
            as_of_date=date(2026, 8, 28),
            exposure_score=72.0,
            stance="Confirmed Uptrend",
        )
    )
    collector, rs_reader, batch = _collector(
        provider,
        resolution=_canonical_resolution(("AAPL",)),
        exposure_reader=exposure_reader,
    )

    with pytest.raises(ProspectiveShadowIntegrityError, match="wrong identity"):
        collector.collect(symbols=["AAPL"], as_of_date=AS_OF, run_ref="run:1")

    assert provider.prepare_kwargs is None
    assert rs_reader.calls == []
    assert batch.calls == []


def test_rejects_optional_context_for_unrequested_symbol():
    provider = _FakeProvider({"AAPL": _stock_data("AAPL")})
    collector, _, batch = _collector(
        provider,
        resolution=_canonical_resolution(("AAPL",)),
    )

    with pytest.raises(ValueError, match="unrequested symbol: MSFT"):
        collector.collect(
            symbols=["AAPL"],
            as_of_date=AS_OF,
            run_ref="run:1",
            group_rank_by_symbol={"MSFT": 2},
        )

    assert batch.calls == []
