"""Static-site breadth backfill readiness assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class StaticBreadthBackfillAssessment:
    minimum_stocks_scanned: int
    hard_error_dates: tuple[date, ...] = ()
    tolerated_error_dates: tuple[date, ...] = ()
    undercovered_dates: tuple[date, ...] = ()
    unclassified_error_count: int = 0
    error: str | None = None

    @property
    def status(self) -> str:
        return "errored" if self.error else "completed"

    @property
    def ready_for_exposure(self) -> bool:
        return self.error is None

    def diagnostics(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "minimum_stocks_scanned": self.minimum_stocks_scanned,
            "hard_error_dates": [
                calc_date.isoformat()
                for calc_date in self.hard_error_dates
            ],
            "unclassified_error_count": self.unclassified_error_count,
        }
        if self.tolerated_error_dates:
            payload["tolerated_error_dates"] = [
                calc_date.isoformat()
                for calc_date in self.tolerated_error_dates
            ]
        if self.undercovered_dates:
            payload["undercovered_dates"] = [
                calc_date.isoformat()
                for calc_date in self.undercovered_dates
            ]
        return payload


def classify_static_breadth_backfill(
    *,
    stats: Mapping[str, Any],
    dates: Sequence[date],
    as_of_date: date,
    minimum_stocks_scanned: int,
    scanned_by_date: Mapping[date, int],
) -> StaticBreadthBackfillAssessment:
    error_dates = _static_breadth_error_dates(stats)
    hard_error_dates: list[date] = []
    tolerated_error_dates: list[date] = []
    undercovered_dates: list[date] = []
    has_seen_valid_history = False
    should_validate_undercoverage = static_breadth_backfill_validates_undercoverage(
        stats,
        minimum_stocks_scanned=minimum_stocks_scanned,
    )

    for calc_date in sorted(set(dates)):
        if calc_date in error_dates:
            if calc_date == as_of_date or has_seen_valid_history:
                hard_error_dates.append(calc_date)
            else:
                tolerated_error_dates.append(calc_date)
            continue

        if _static_breadth_row_has_accepted_coverage(
            scanned_by_date.get(calc_date),
            minimum_stocks_scanned=minimum_stocks_scanned,
        ):
            has_seen_valid_history = True
            continue

        if (
            should_validate_undercoverage
            and (calc_date == as_of_date or has_seen_valid_history)
        ):
            undercovered_dates.append(calc_date)

    hard_error_dates_tuple = tuple(hard_error_dates)
    tolerated_error_dates_tuple = tuple(tolerated_error_dates)
    undercovered_dates_tuple = tuple(undercovered_dates)
    unclassified_error_count = _static_breadth_unclassified_error_count(
        stats,
        classified_error_dates=error_dates,
    )
    return StaticBreadthBackfillAssessment(
        minimum_stocks_scanned=minimum_stocks_scanned,
        hard_error_dates=hard_error_dates_tuple,
        tolerated_error_dates=tolerated_error_dates_tuple,
        undercovered_dates=undercovered_dates_tuple,
        unclassified_error_count=unclassified_error_count,
        error=_static_breadth_backfill_error(
            stats,
            minimum_stocks_scanned=minimum_stocks_scanned,
            hard_error_dates=hard_error_dates_tuple,
            undercovered_dates=undercovered_dates_tuple,
            unclassified_error_count=unclassified_error_count,
        ),
    )


def static_breadth_row_has_accepted_coverage(
    total_stocks_scanned: int | None,
    *,
    minimum_stocks_scanned: int,
) -> bool:
    return _static_breadth_row_has_accepted_coverage(
        total_stocks_scanned,
        minimum_stocks_scanned=minimum_stocks_scanned,
    )


def static_breadth_backfill_needs_scan_counts(
    stats: Mapping[str, Any],
    *,
    minimum_stocks_scanned: int,
) -> bool:
    return bool(_static_breadth_error_dates(stats)) or (
        static_breadth_backfill_validates_undercoverage(
            stats,
            minimum_stocks_scanned=minimum_stocks_scanned,
        )
    )


def static_breadth_backfill_validates_undercoverage(
    stats: Mapping[str, Any],
    *,
    minimum_stocks_scanned: int,
) -> bool:
    return (
        int(stats.get("insufficient_history_observations") or 0) > 0
        and minimum_stocks_scanned > 0
    )


def _static_breadth_row_has_accepted_coverage(
    total_stocks_scanned: int | None,
    *,
    minimum_stocks_scanned: int,
) -> bool:
    return (
        minimum_stocks_scanned > 0
        and int(total_stocks_scanned or 0) >= minimum_stocks_scanned
    )


def _static_breadth_backfill_error(
    stats: Mapping[str, Any],
    *,
    minimum_stocks_scanned: int,
    hard_error_dates: tuple[date, ...],
    undercovered_dates: tuple[date, ...],
    unclassified_error_count: int,
) -> str | None:
    calculation_errors = int(stats.get("error_stocks") or 0)
    if calculation_errors > 0:
        return (
            "Cache-only breadth backfill has calculation errors "
            f"(error_stocks={calculation_errors})"
        )

    if hard_error_dates:
        date_sample = ",".join(
            calc_date.isoformat()
            for calc_date in hard_error_dates
        )
        return (
            "Cache-only breadth backfill has hard date errors "
            f"(dates={date_sample})"
        )

    if unclassified_error_count > 0:
        return (
            "Cache-only breadth backfill has errors "
            f"(errors={unclassified_error_count})"
        )

    total_dates = int(stats.get("total_dates") or 0)
    processed = int(stats.get("processed") or 0)
    if total_dates > 0 and processed == 0:
        return "Cache-only breadth backfill processed no dates"

    if undercovered_dates:
        date_sample = ",".join(
            calc_date.isoformat()
            for calc_date in undercovered_dates
        )
        return (
            "Cache-only breadth backfill has insufficient usable coverage "
            f"(dates={date_sample}, "
            f"minimum_scanned={minimum_stocks_scanned})"
        )

    target_symbols = stats.get("target_symbols")
    if target_symbols is None:
        return None

    total_symbols = int(target_symbols or 0)
    if total_symbols == 0:
        return "Cache-only breadth backfill processed no stocks"

    cache_misses = int(stats.get("cache_miss_stocks") or 0)
    max_cache_misses = max(
        0,
        total_symbols - minimum_stocks_scanned,
    )
    if cache_misses > max_cache_misses:
        miss_ratio = cache_misses / total_symbols
        miss_limit = max_cache_misses / total_symbols
        return (
            "Cache-only breadth backfill exceeds miss tolerance "
            f"(cache_misses={cache_misses}, total={total_symbols}, "
            f"ratio={miss_ratio:.1%}, "
            f"limit={miss_limit:.0%})"
        )
    return None


def _static_breadth_error_dates(stats: Mapping[str, Any]) -> set[date]:
    raw_error_dates = stats.get("error_dates")
    if not isinstance(raw_error_dates, list):
        return set()

    error_dates: set[date] = set()
    for raw_error_date in raw_error_dates:
        if not isinstance(raw_error_date, str):
            continue
        try:
            error_dates.add(date.fromisoformat(raw_error_date))
        except ValueError:
            continue
    return error_dates


def _static_breadth_unclassified_error_count(
    stats: Mapping[str, Any],
    *,
    classified_error_dates: set[date],
) -> int:
    errors = int(stats.get("errors") or 0)
    return max(0, errors - len(classified_error_dates))
