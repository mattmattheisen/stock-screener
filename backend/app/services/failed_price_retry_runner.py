"""Bounded execution for retrying failed price symbols."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from .price_fetch_failures import is_retryable_price_failure
from .price_refresh_execution import (
    PriceBatchCache,
    PriceBatchFetcher,
    PriceRefreshBatchExecutionError,
    PriceRefreshBatchExecutor,
    PriceRefreshBatchOutcome,
    PriceRefreshExecutionSummary,
    SymbolFailureTracker,
)
from .price_refresh_planning import PriceRefreshJob, PriceRefreshJobKind


@dataclass(frozen=True)
class FailedPriceRetryRunnerDependencies:
    fetch_with_backoff: PriceBatchFetcher
    track_symbol_failures: SymbolFailureTracker
    raise_if_transient_database_error: Callable[[Exception], None]
    schedule_failed_symbol_retry: Callable[..., None]


@dataclass(frozen=True)
class FailedPriceRetryResult:
    refreshed: int
    failed: int
    failed_symbols: tuple[str, ...]
    error: str | None = None

    @property
    def status(self) -> str:
        return "completed" if self.failed == 0 else "partial"


class FailedPriceRetryRunner:
    def __init__(self, dependencies: FailedPriceRetryRunnerDependencies) -> None:
        self._deps = dependencies

    def run(
        self,
        *,
        price_cache: PriceBatchCache,
        bulk_fetcher: Any,
        symbols: Sequence[str],
        market: str,
        attempt: int,
        retry_countdown: int,
        batch_size: int,
    ) -> FailedPriceRetryResult:
        retry_job = PriceRefreshJob(
            kind=PriceRefreshJobKind.NO_HISTORY,
            symbols=tuple(symbols),
            period="2y",
        )
        retryable_failed_symbols: list[str] = []

        def after_batch(
            outcome: PriceRefreshBatchOutcome,
            _summary: PriceRefreshExecutionSummary,
        ) -> None:
            retryable_failed_symbols.extend(
                symbol
                for symbol in outcome.failures
                if is_retryable_price_failure(
                    kind=outcome.failure_kinds.get(symbol),
                    error=outcome.failure_details.get(symbol, ""),
                )
            )

        try:
            summary = PriceRefreshBatchExecutor(
                fetch_with_backoff=self._deps.fetch_with_backoff,
                track_symbol_failures=self._deps.track_symbol_failures,
                raise_if_transient_database_error=(
                    self._deps.raise_if_transient_database_error
                ),
            ).run(
                bulk_fetcher=bulk_fetcher,
                price_cache=price_cache,
                db=None,
                jobs=(retry_job,),
                total=len(symbols),
                batch_size=max(1, int(batch_size)),
                market=market,
                market_for_symbol=lambda _symbol: market,
                after_batch=after_batch,
            )
        except PriceRefreshBatchExecutionError as exc:
            if isinstance(exc.cause, SoftTimeLimitExceeded):
                raise exc.cause
            symbols_to_retry = tuple(
                dict.fromkeys(
                    [*retryable_failed_symbols, *exc.unresolved_symbols]
                )
            )
            self._schedule_retry(
                symbols_to_retry,
                market=market,
                attempt=attempt,
                retry_countdown=retry_countdown,
            )
            return FailedPriceRetryResult(
                refreshed=exc.summary.refreshed,
                failed=exc.summary.failed + len(exc.unresolved_symbols),
                failed_symbols=(
                    tuple(exc.summary.failed_symbols) + exc.unresolved_symbols
                ),
                error=str(exc.cause),
            )

        self._schedule_retry(
            retryable_failed_symbols,
            market=market,
            attempt=attempt,
            retry_countdown=retry_countdown,
        )
        return FailedPriceRetryResult(
            refreshed=summary.refreshed,
            failed=summary.failed,
            failed_symbols=tuple(summary.failed_symbols),
        )

    def _schedule_retry(
        self,
        symbols: Sequence[str],
        *,
        market: str,
        attempt: int,
        retry_countdown: int,
    ) -> None:
        if not symbols or attempt >= 3:
            return
        self._deps.schedule_failed_symbol_retry(
            list(symbols),
            market=market,
            attempt=attempt + 1,
            countdown=retry_countdown,
        )
