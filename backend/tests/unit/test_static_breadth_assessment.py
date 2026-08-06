from datetime import date

from app.services.static_breadth_assessment import (
    classify_static_breadth_backfill,
)


def _backfill_stats(**overrides):
    stats = {
        "total_dates": 1,
        "processed": 1,
        "errors": 0,
        "error_dates": [],
        "target_symbols": 10,
        "symbols_with_cached_history": 10,
        "cache_miss_stocks": 0,
        "error_stocks": 0,
        "cache_coverage_ratio": 1.0,
        "insufficient_history_observations": 0,
    }
    stats.update(overrides)
    return stats


def test_static_breadth_assessment_tolerates_only_pre_warmup_error_dates():
    pre_warmup_error_date = date(2026, 7, 27)
    covered_date = date(2026, 7, 28)
    post_warmup_error_date = date(2026, 7, 30)
    as_of_date = date(2026, 7, 31)

    assessment = classify_static_breadth_backfill(
        stats=_backfill_stats(
            total_dates=4,
            processed=2,
            errors=2,
            error_dates=[
                pre_warmup_error_date.isoformat(),
                post_warmup_error_date.isoformat(),
            ],
            insufficient_history_observations=10,
        ),
        dates=[
            pre_warmup_error_date,
            covered_date,
            post_warmup_error_date,
            as_of_date,
        ],
        as_of_date=as_of_date,
        minimum_stocks_scanned=9,
        scanned_by_date={
            covered_date: 10,
            as_of_date: 10,
        },
    )

    assert assessment.status == "errored"
    assert assessment.tolerated_error_dates == (pre_warmup_error_date,)
    assert assessment.hard_error_dates == (post_warmup_error_date,)
    assert assessment.diagnostics()["tolerated_error_dates"] == ["2026-07-27"]
    assert assessment.diagnostics()["hard_error_dates"] == ["2026-07-30"]
    assert assessment.error == (
        "Cache-only breadth backfill has hard date errors "
        "(dates=2026-07-30)"
    )


def test_static_breadth_assessment_tolerates_pre_warmup_undercoverage():
    pre_warmup_gap_date = date(2026, 7, 30)
    as_of_date = date(2026, 7, 31)

    assessment = classify_static_breadth_backfill(
        stats=_backfill_stats(
            total_dates=2,
            processed=2,
            insufficient_history_observations=9,
        ),
        dates=[pre_warmup_gap_date, as_of_date],
        as_of_date=as_of_date,
        minimum_stocks_scanned=8,
        scanned_by_date={
            pre_warmup_gap_date: 1,
            as_of_date: 10,
        },
    )

    assert assessment.status == "completed"
    assert assessment.undercovered_dates == ()
    assert assessment.error is None


def test_static_breadth_assessment_rejects_undercoverage_after_warmup():
    warmup_date = date(2026, 7, 27)
    covered_date = date(2026, 7, 28)
    recent_gap_date = date(2026, 7, 30)
    as_of_date = date(2026, 7, 31)

    assessment = classify_static_breadth_backfill(
        stats=_backfill_stats(
            total_dates=4,
            processed=4,
            insufficient_history_observations=10,
        ),
        dates=[
            warmup_date,
            covered_date,
            recent_gap_date,
            as_of_date,
        ],
        as_of_date=as_of_date,
        minimum_stocks_scanned=8,
        scanned_by_date={
            warmup_date: 1,
            covered_date: 10,
            recent_gap_date: 1,
            as_of_date: 10,
        },
    )

    assert assessment.status == "errored"
    assert assessment.undercovered_dates == (recent_gap_date,)
    assert assessment.error == (
        "Cache-only breadth backfill has insufficient usable coverage "
        "(dates=2026-07-30, minimum_scanned=8)"
    )


def test_static_breadth_assessment_keeps_unclassified_errors_hard():
    as_of_date = date(2026, 7, 31)

    assessment = classify_static_breadth_backfill(
        stats=_backfill_stats(
            errors=1,
        ),
        dates=[as_of_date],
        as_of_date=as_of_date,
        minimum_stocks_scanned=9,
        scanned_by_date={},
    )

    assert assessment.status == "errored"
    assert assessment.unclassified_error_count == 1
    assert assessment.error == (
        "Cache-only breadth backfill has errors (errors=1)"
    )
