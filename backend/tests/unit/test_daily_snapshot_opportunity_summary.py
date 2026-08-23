"""Daily Snapshot correction-survivor summary behavior."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

import app.services.daily_snapshot_service as daily_snapshot_service
from app.domain.common.query import (
    BooleanFilter,
    CategoricalFilter,
    RangeFilter,
    SortOrder,
)
from app.domain.scanning.models import ResultPage, ScanResultItemDomain
from app.domain.scanning.opportunity_state import ActionState
from app.domain.scanning.opportunity_summary import OpportunityStateSummary
from app.schemas.market_scan import DailySnapshotResponse
from app.use_cases.scanning.get_scan_results import GetScanResultsResult


class FakeDailySnapshotScanResults:
    """In-memory query service fake that honors the production query contract."""

    def __init__(self, rows):
        self.rows = tuple(rows)
        self.calls = 0

    def execute(self, _uow, query):
        self.calls += 1
        rows = list(self.rows)
        for condition in query.query_spec.expression.required_conditions:
            if isinstance(condition, BooleanFilter):
                rows = [
                    row
                    for row in rows
                    if row.extended_fields.get(condition.field) is condition.value
                ]
            elif isinstance(condition, CategoricalFilter):
                rows = [
                    row
                    for row in rows
                    if row.extended_fields.get(condition.field) in condition.values
                ]
            elif isinstance(condition, RangeFilter):
                rows = [
                    row
                    for row in rows
                    if self._range_value(row, condition.field) is not None
                    and (
                        condition.min_value is None
                        or self._range_value(row, condition.field)
                        >= condition.min_value
                    )
                    and (
                        condition.max_value is None
                        or self._range_value(row, condition.field)
                        <= condition.max_value
                    )
                ]
            else:  # pragma: no cover - protects this fake from silent contract drift.
                raise TypeError(f"Unhandled test query condition: {condition!r}")

        total = len(rows)
        rows.sort(key=lambda row: str(row.symbol))
        sort = query.query_spec.sort
        rows.sort(
            key=lambda row: self._sort_value(row, sort.field),
            reverse=sort.order == SortOrder.DESC,
        )
        page = query.query_spec.page
        items = tuple(rows[page.offset : page.offset + page.limit])
        return GetScanResultsResult(
            page=ResultPage(
                items=items,
                total=total,
                page=page.page,
                per_page=page.per_page,
            ),
            unfiltered_total=len(self.rows),
            query_fingerprint="fake-daily-snapshot-query",
        )

    @staticmethod
    def _range_value(row, field):
        if field == "volume":
            return row.extended_fields.get("volume")
        return row.extended_fields.get(field)

    @staticmethod
    def _sort_value(row, field):
        if field == "composite_score":
            return (
                row.composite_score
                if row.composite_score is not None
                else float("-inf")
            )
        value = row.extended_fields.get(field)
        return value if value is not None else float("-inf")


class FakeDailyOpportunitySummaryReader:
    """Aggregate persisted projection rows without reusing query behavior."""

    def __init__(self, rows):
        self.rows = tuple(rows)
        self.calls = 0

    def for_scan(self, _scan_id):
        self.calls += 1
        action_state_counts = {state: 0 for state in ActionState}
        survivor_action_state_counts = {state: 0 for state in ActionState}
        survivor_count = 0
        for row in self.rows:
            fields = row.extended_fields
            try:
                action_state = ActionState(fields.get("action_state"))
            except ValueError:
                continue
            action_state_counts[action_state] += 1
            if fields.get("correction_survivor") is True:
                survivor_count += 1
                survivor_action_state_counts[action_state] += 1
        return OpportunityStateSummary(
            rows_total=len(self.rows),
            survivor_count=survivor_count,
            action_state_counts=action_state_counts,
            survivor_action_state_counts=survivor_action_state_counts,
        )

    def for_feature_run(self, _run_id):  # pragma: no cover - contract guard
        raise AssertionError("Daily snapshots aggregate by scan, not feature run")


def _daily_snapshot_row(
    symbol,
    *,
    survivor,
    resilience,
    action_state,
    composite_score=75.0,
):
    score_pillars = {
        "benchmark_leadership": resilience,
        "multi_horizon_rs": 0.0 if resilience is not None else None,
        "trend_integrity": 0.0 if resilience is not None else None,
        "structure_tightness": 0.0 if resilience is not None else None,
        "liquidity_freshness": 0.0 if resilience is not None else None,
    }
    return ScanResultItemDomain(
        symbol=symbol,
        composite_score=composite_score,
        rating="Buy",
        current_price=100.0,
        screener_outputs={},
        screeners_run=["minervini"],
        composite_method="weighted_average",
        screeners_passed=1,
        screeners_total=1,
        extended_fields={
            "company_name": f"{symbol} Holdings",
            "volume": 200_000_000,
            "correction_survivor": survivor,
            "resilience_score": resilience,
            "action_state": action_state,
            "opportunity_state": {
                "schema_version": 1,
                "policy_version": "correction-survivors-v1",
                "as_of_date": "2026-08-21",
                "market": "US",
                "mic": "XNAS",
                "benchmark_symbol": "SPY",
                "benchmark_as_of_date": "2026-08-21",
                "passed_checks": [],
                "failed_checks": [],
                "warnings": [],
                "score_pillars": score_pillars,
                "metrics": {},
                "data_availability": {"required_evidence": "complete"},
                "action_reasons": [action_state],
            },
        },
    )


@pytest.fixture
def survivor_snapshot_fixture(monkeypatch):
    rows = [
        _daily_snapshot_row(
            "CCC",
            survivor=True,
            resilience=81.0,
            action_state="event_risk",
            composite_score=99.0,
        ),
        _daily_snapshot_row(
            "BBB",
            survivor=True,
            resilience=88.0,
            action_state="watch",
            composite_score=50.0,
        ),
        _daily_snapshot_row(
            "AAA",
            survivor=True,
            resilience=88.0,
            action_state="setup_ready",
            composite_score=10.0,
        ),
        _daily_snapshot_row(
            "ZZZ", survivor=False, resilience=99.0, action_state="watch"
        ),
    ]
    scan = SimpleNamespace(
        scan_id="scan-survivors",
        feature_run_id=1,
        metadata_json=None,
        feature_run=SimpleNamespace(
            as_of_date=date(2026, 8, 21),
            published_at=datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc),
            config_json={"materialization_versions": {"opportunity_state": 1}},
        ),
        completed_at=datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        daily_snapshot_service,
        "_build_top_groups",
        lambda *_args, **_kwargs: ([], None),
    )
    monkeypatch.setattr(
        daily_snapshot_service,
        "_latest_breadth_date",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        daily_snapshot_service,
        "build_key_market_entries",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        daily_snapshot_service,
        "build_exposure_payload",
        lambda *_args, **_kwargs: {
            "market": "US",
            "date": "2026-08-21",
            "exposure_score": 50.0,
            "stance": "neutral",
            "distribution_day_count": 3,
            "follow_through_day": False,
            "history": [],
        },
    )
    return {
        "db": object(),
        "market": "US",
        "market_display_name": "United States",
        "scan": scan,
        "uow": object(),
        "scan_results_use_case": FakeDailySnapshotScanResults(rows),
        "opportunity_summary_reader": FakeDailyOpportunitySummaryReader(rows),
    }


class TestDailySnapshotCorrectionSurvivors:
    def test_contains_ranked_persisted_survivor_summary(
        self, survivor_snapshot_fixture
    ):
        payload = daily_snapshot_service.build_daily_snapshot_payload(
            **survivor_snapshot_fixture
        )
        validated = DailySnapshotResponse.model_validate(payload)

        assert payload["correction_survivors"] == {
            "available": True,
            "complete": True,
            "count": 3,
            "counts_by_action_state": {
                "exit_risk": 0,
                "deteriorating": 0,
                "event_risk": 1,
                "extended": 0,
                "data_limited": 0,
                "setup_ready": 1,
                "watch": 1,
            },
            "rows": payload["correction_survivors"]["rows"],
        }
        assert [row["symbol"] for row in payload["correction_survivors"]["rows"]] == [
            "AAA",
            "BBB",
            "CCC",
        ]
        assert validated.correction_survivors.count == 3
        # Top candidates + leaders + one survivor-row query. Counts come from
        # the aggregate summary reader, not seven extra result queries.
        assert survivor_snapshot_fixture["scan_results_use_case"].calls == 3

    def test_survivor_rows_are_limited_to_top_twenty(self, survivor_snapshot_fixture):
        rows = [
            _daily_snapshot_row(
                f"A{index:02d}",
                survivor=True,
                resilience=100.0 - index,
                action_state="setup_ready",
            )
            for index in range(22)
        ]
        survivor_snapshot_fixture["scan_results_use_case"] = (
            FakeDailySnapshotScanResults(rows)
        )
        survivor_snapshot_fixture["opportunity_summary_reader"] = (
            FakeDailyOpportunitySummaryReader(rows)
        )

        summary = daily_snapshot_service.build_daily_snapshot_payload(
            **survivor_snapshot_fixture
        )["correction_survivors"]

        assert summary["count"] == 22
        assert [row["symbol"] for row in summary["rows"]] == [
            "A00",
            "A01",
            "A02",
            "A03",
            "A04",
            "A05",
            "A06",
            "A07",
            "A08",
            "A09",
            "A10",
            "A11",
            "A12",
            "A13",
            "A14",
            "A15",
            "A16",
            "A17",
            "A18",
            "A19",
        ]

    def test_existing_scan_with_zero_survivors_is_available_and_complete(
        self, survivor_snapshot_fixture
    ):
        survivor_snapshot_fixture["scan_results_use_case"] = (
            FakeDailySnapshotScanResults([])
        )
        survivor_snapshot_fixture["opportunity_summary_reader"] = (
            FakeDailyOpportunitySummaryReader([])
        )

        payload = daily_snapshot_service.build_daily_snapshot_payload(
            **survivor_snapshot_fixture
        )

        assert payload["correction_survivors"] == {
            "available": True,
            "complete": True,
            "count": 0,
            "counts_by_action_state": {
                "exit_risk": 0,
                "deteriorating": 0,
                "event_risk": 0,
                "extended": 0,
                "data_limited": 0,
                "setup_ready": 0,
                "watch": 0,
            },
            "rows": [],
        }

    def test_no_scan_marks_survivor_summary_unavailable(
        self, survivor_snapshot_fixture
    ):
        survivor_snapshot_fixture["scan"] = None

        payload = daily_snapshot_service.build_daily_snapshot_payload(
            **survivor_snapshot_fixture
        )

        assert payload["correction_survivors"] == {
            "available": False,
            "complete": False,
            "count": 0,
            "counts_by_action_state": {
                "exit_risk": 0,
                "deteriorating": 0,
                "event_risk": 0,
                "extended": 0,
                "data_limited": 0,
                "setup_ready": 0,
                "watch": 0,
            },
            "rows": [],
        }

    def test_legacy_scan_marks_summary_unavailable_without_count_queries(
        self, survivor_snapshot_fixture
    ):
        scan = survivor_snapshot_fixture["scan"]
        scan.feature_run.config_json = {}
        use_case = survivor_snapshot_fixture["scan_results_use_case"]

        summary = daily_snapshot_service._build_correction_survivor_summary(
            scan=scan,
            uow=survivor_snapshot_fixture["uow"],
            scan_results_use_case=use_case,
        )

        assert summary == {
            "available": False,
            "complete": False,
            "count": 0,
            "counts_by_action_state": {
                "exit_risk": 0,
                "deteriorating": 0,
                "event_risk": 0,
                "extended": 0,
                "data_limited": 0,
                "setup_ready": 0,
                "watch": 0,
            },
            "rows": [],
        }
        assert use_case.calls == 0

    def test_missing_market_posture_does_not_alter_survivors(
        self, survivor_snapshot_fixture, monkeypatch
    ):
        with_posture = daily_snapshot_service.build_daily_snapshot_payload(
            **survivor_snapshot_fixture
        )["correction_survivors"]
        monkeypatch.setattr(
            daily_snapshot_service,
            "build_exposure_payload",
            lambda *_args, **_kwargs: None,
        )

        without_posture = daily_snapshot_service.build_daily_snapshot_payload(
            **survivor_snapshot_fixture
        )["correction_survivors"]

        assert without_posture == with_posture
