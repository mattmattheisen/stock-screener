"""Tests for execution-scoped benchmark remote-fetch suppression."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from app.services.benchmark_resolution import (
    BenchmarkCandidateSource,
    BenchmarkResolver,
    benchmark_remote_fetch_allowed,
    benchmark_remote_fetch_disabled,
)


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [101.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [100.5, 101.5],
            "Volume": [1_000_000, 1_100_000],
        },
        index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
    )


class _Registry:
    def normalize_market(self, market: str) -> str:
        return market.upper()

    def get_entry(self, market: str):
        return SimpleNamespace(primary_kind="etf", fallback_kind="index")

    def get_candidate_symbols(self, market: str):
        return ["SPY", "^GSPC"]


class _Adapter:
    def __init__(self, *, redis_data=None, database_data=None, fetched_data=None):
        self.redis_data = redis_data
        self.database_data = database_data
        self.fetched_data = fetched_data
        self.fetch_calls = 0
        self.redis_writes = 0

    def load_benchmark_from_redis(self, benchmark_symbol, period, market):
        return self.redis_data

    def load_benchmark_from_database(self, benchmark_symbol, period, market="US"):
        return self.database_data

    def benchmark_data_is_fresh(self, data, market="US", max_age_hours=24):
        return True

    def store_benchmark_in_redis(self, benchmark_symbol, period, data, market="US"):
        self.redis_writes += 1

    def fetch_and_cache_benchmark(
        self,
        benchmark_symbol,
        market,
        period,
        required_as_of_date=None,
    ):
        self.fetch_calls += 1
        return self.fetched_data


def _resolver(adapter: _Adapter) -> BenchmarkResolver:
    return BenchmarkResolver(adapter=adapter, registry=_Registry())


def test_remote_fetch_guard_fails_closed_on_cache_miss():
    adapter = _Adapter(fetched_data=_prices())

    assert benchmark_remote_fetch_allowed() is True
    with benchmark_remote_fetch_disabled():
        assert benchmark_remote_fetch_allowed() is False
        resolution = _resolver(adapter).resolve(market="US")

    assert benchmark_remote_fetch_allowed() is True
    assert resolution.bundle is None
    assert resolution.error == "no_benchmark_data"
    assert adapter.fetch_calls == 0


def test_remote_fetch_guard_still_allows_cached_benchmark():
    adapter = _Adapter(redis_data=_prices(), fetched_data=_prices())

    with benchmark_remote_fetch_disabled():
        resolution = _resolver(adapter).resolve(market="US")

    assert resolution.bundle is not None
    assert resolution.bundle.benchmark_symbol == "SPY"
    assert resolution.bundle.candidate_statuses[-1].source == BenchmarkCandidateSource.REDIS
    assert adapter.fetch_calls == 0


def test_remote_fetch_guard_allows_database_cache_and_existing_redis_promotion():
    adapter = _Adapter(database_data=_prices(), fetched_data=_prices())

    with benchmark_remote_fetch_disabled():
        resolution = _resolver(adapter).resolve(market="US")

    assert resolution.bundle is not None
    assert resolution.bundle.candidate_statuses[-1].source == BenchmarkCandidateSource.DATABASE
    assert adapter.redis_writes == 1
    assert adapter.fetch_calls == 0


def test_default_resolution_behavior_still_fetches_on_cache_miss():
    adapter = _Adapter(fetched_data=_prices())

    resolution = _resolver(adapter).resolve(market="US")

    assert resolution.bundle is not None
    assert resolution.bundle.candidate_statuses[-1].source == BenchmarkCandidateSource.FETCH
    assert adapter.fetch_calls == 1


def test_force_refresh_cannot_bypass_remote_fetch_guard():
    adapter = _Adapter(redis_data=_prices(), fetched_data=_prices())

    with benchmark_remote_fetch_disabled():
        resolution = _resolver(adapter).resolve(market="US", force_refresh=True)

    assert resolution.bundle is None
    assert resolution.error == "no_benchmark_data"
    assert adapter.fetch_calls == 0
