from __future__ import annotations

def test_retry_task_normalizes_input_and_maps_runner_result(monkeypatch):
    import app.tasks.cache_tasks as module
    from app.services.failed_price_retry_runner import FailedPriceRetryResult

    captured = {}

    class RecordingRunner:
        def __init__(self, dependencies):
            captured["dependencies"] = dependencies

        def run(self, **kwargs):
            captured["run"] = kwargs
            return FailedPriceRetryResult(
                refreshed=2,
                failed=1,
                failed_symbols=("META",),
                error="storage unavailable",
            )

    monkeypatch.setattr(module, "FailedPriceRetryRunner", RecordingRunner)
    monkeypatch.setattr(module.settings, "price_refresh_live_batch_size", 75)
    monkeypatch.setattr(
        "app.wiring.bootstrap.get_price_cache",
        lambda: "price-cache",
    )
    monkeypatch.setattr(
        "app.services.bulk_data_fetcher.BulkDataFetcher",
        lambda: "bulk-fetcher",
    )

    result = module.retry_failed_price_symbols.run.__wrapped__(
        module.retry_failed_price_symbols,
        symbols=["aapl", "AAPL", "meta"],
        market="US",
        attempt=2,
        retry_countdown=30,
    )

    assert captured["run"] == {
        "price_cache": "price-cache",
        "bulk_fetcher": "bulk-fetcher",
        "symbols": ["AAPL", "META"],
        "market": "US",
        "attempt": 2,
        "retry_countdown": 30,
        "batch_size": 75,
    }
    assert result["status"] == "partial"
    assert result["market"] == "US"
    assert result["attempt"] == 2
    assert result["refreshed"] == 2
    assert result["failed"] == 1
    assert result["failed_symbols"] == ["META"]
    assert result["error"] == "storage unavailable"
    assert result["completed_at"]


def test_retry_task_returns_without_constructing_runner_for_empty_symbols(monkeypatch):
    import app.tasks.cache_tasks as module

    monkeypatch.setattr(
        module,
        "FailedPriceRetryRunner",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("empty input must not construct the runner")
        ),
    )

    result = module.retry_failed_price_symbols.run.__wrapped__(
        module.retry_failed_price_symbols,
        symbols=["", ""],
        market="JP",
        attempt=3,
    )

    assert result == {
        "status": "completed",
        "market": "JP",
        "attempt": 3,
        "refreshed": 0,
        "failed": 0,
    }
