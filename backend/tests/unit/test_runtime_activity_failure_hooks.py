from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from celery.exceptions import Retry
from celery.worker.request import Request


SMART_REFRESH_TASK = "app.tasks.cache_tasks.smart_refresh_cache"
FAILED_PRICE_RETRY_TASK = "app.tasks.cache_tasks.retry_failed_price_symbols"


def _patch_failure_dependencies(monkeypatch, module):
    harness = SimpleNamespace(
        db=MagicMock(),
        failed_activity_calls=[],
        lock=MagicMock(),
        coordination=MagicMock(),
        price_cache=MagicMock(),
    )

    monkeypatch.setattr(module, "SessionLocal", lambda: harness.db)
    monkeypatch.setattr(module, "get_data_fetch_lock", lambda: harness.lock)
    monkeypatch.setattr(module, "get_workload_coordination", lambda: harness.coordination)
    monkeypatch.setattr(module, "get_price_cache", lambda: harness.price_cache)
    monkeypatch.setattr(
        module,
        "mark_market_activity_failed",
        lambda db_arg, **kwargs: harness.failed_activity_calls.append((db_arg, kwargs)),
    )

    return harness


def test_publish_runtime_activity_failure_marks_smart_refresh_failed(monkeypatch):
    import app.tasks.runtime_activity_failure_hooks as module

    harness = _patch_failure_dependencies(monkeypatch, module)

    module.publish_runtime_activity_failure(
        SMART_REFRESH_TASK,
        "lost-task",
        {"market": "us", "activity_lifecycle": "bootstrap"},
        RuntimeError("Worker exited prematurely: signal 9 (SIGKILL)"),
    )

    assert harness.failed_activity_calls == [
        (
            harness.db,
            {
                "market": "US",
                "stage_key": "prices",
                "lifecycle": "bootstrap",
                "task_name": SMART_REFRESH_TASK,
                "task_id": "lost-task",
                "message": (
                    "Task worker exited before cleanup: "
                    "Worker exited prematurely: signal 9 (SIGKILL)"
                ),
            },
        )
    ]
    harness.price_cache.complete_warmup_heartbeat.assert_called_once_with("failed", market="US")
    harness.lock.release.assert_called_once_with("lost-task", market="US")
    harness.coordination.release_market_workload.assert_called_once_with("lost-task", market="US")
    harness.coordination.release_external_fetch.assert_called_once_with("lost-task")
    harness.db.close.assert_called_once_with()


def test_publish_runtime_activity_failure_keeps_shared_cleanup_scope_for_missing_market(
    monkeypatch,
):
    import app.tasks.runtime_activity_failure_hooks as module

    harness = _patch_failure_dependencies(monkeypatch, module)

    module.publish_runtime_activity_failure(
        SMART_REFRESH_TASK,
        "shared-task",
        {"mode": "auto"},
        RuntimeError("worker lost"),
    )

    assert harness.failed_activity_calls[0][1]["market"] == "US"
    harness.price_cache.complete_warmup_heartbeat.assert_called_once_with("failed", market=None)
    harness.lock.release.assert_called_once_with("shared-task", market=None)
    harness.coordination.release_market_workload.assert_called_once_with(
        "shared-task",
        market=None,
    )
    harness.coordination.release_external_fetch.assert_called_once_with("shared-task")
    harness.db.close.assert_called_once_with()


def test_failed_price_retry_worker_loss_releases_resources_without_publishing_activity(
    monkeypatch,
):
    import app.tasks.cache_tasks as cache_tasks
    import app.tasks.runtime_activity_failure_hooks as module

    harness = _patch_failure_dependencies(monkeypatch, module)
    monkeypatch.setattr(
        Request,
        "on_failure",
        lambda self, exc_info, send_failed_event=True, return_ok=False: "super-result",
    )

    request = object.__new__(cache_tasks.retry_failed_price_symbols.Request)
    request._task = SimpleNamespace(name=FAILED_PRICE_RETRY_TASK)
    request.id = "lost-retry-task"
    request._kwargs = {"market": "US"}

    result = request.on_failure(
        SimpleNamespace(
            exception=RuntimeError("Worker exited prematurely: signal 9 (SIGKILL)")
        )
    )

    assert result == "super-result"
    assert harness.failed_activity_calls == []
    harness.price_cache.complete_warmup_heartbeat.assert_not_called()
    harness.lock.release.assert_called_once_with("lost-retry-task", market="US")
    harness.coordination.release_market_workload.assert_called_once_with(
        "lost-retry-task",
        market="US",
    )
    harness.coordination.release_external_fetch.assert_called_once_with(
        "lost-retry-task"
    )
    harness.db.close.assert_not_called()


def test_publish_runtime_activity_failure_ignores_untracked_tasks(monkeypatch):
    import app.tasks.runtime_activity_failure_hooks as module

    monkeypatch.setattr(
        module,
        "SessionLocal",
        lambda: pytest.fail("untracked tasks must not open a database session"),
    )
    monkeypatch.setattr(
        module,
        "mark_market_activity_failed",
        lambda *args, **kwargs: pytest.fail("untracked tasks must not publish activity"),
    )

    module.publish_runtime_activity_failure(
        "app.tasks.cache_tasks.warm_spy_cache",
        "warmup-task",
        {"market": "US"},
        RuntimeError("boom"),
    )


def test_request_hook_delegates_failure_publication(monkeypatch):
    import app.tasks.runtime_activity_failure_hooks as module

    delegated_calls = []

    monkeypatch.setattr(
        Request,
        "on_failure",
        lambda self, exc_info, send_failed_event=True, return_ok=False: "super-result",
    )
    monkeypatch.setattr(
        module,
        "publish_runtime_activity_failure",
        lambda task_name, task_id, kwargs, exception: delegated_calls.append(
            {
                "task_name": task_name,
                "task_id": task_id,
                "kwargs": kwargs,
                "exception": exception,
            }
        ),
    )

    request = object.__new__(module.RuntimeActivityFailureRequest)
    request._task = SimpleNamespace(name=SMART_REFRESH_TASK)
    request.id = "request-task"
    request._kwargs = {"market": "HK", "activity_lifecycle": "bootstrap"}
    exception = RuntimeError("worker disappeared")

    result = request.on_failure(
        SimpleNamespace(exception=exception),
        send_failed_event=False,
        return_ok=True,
    )

    assert result == "super-result"
    assert delegated_calls == [
        {
            "task_name": SMART_REFRESH_TASK,
            "task_id": "request-task",
            "kwargs": {"market": "HK", "activity_lifecycle": "bootstrap"},
            "exception": exception,
        }
    ]


def test_request_hook_skips_failure_publication_for_retry(monkeypatch):
    import app.tasks.runtime_activity_failure_hooks as module

    delegated_calls = []

    monkeypatch.setattr(
        Request,
        "on_failure",
        lambda self, exc_info, send_failed_event=True, return_ok=False: "retry-result",
    )
    monkeypatch.setattr(
        module,
        "publish_runtime_activity_failure",
        lambda *args, **kwargs: delegated_calls.append((args, kwargs)),
    )

    request = object.__new__(module.RuntimeActivityFailureRequest)
    request._task = SimpleNamespace(name=SMART_REFRESH_TASK)
    request.id = "retry-task"
    request._kwargs = {"market": "US"}

    result = request.on_failure(SimpleNamespace(exception=Retry("retry later")))

    assert result == "retry-result"
    assert delegated_calls == []
