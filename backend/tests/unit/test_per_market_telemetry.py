"""Unit tests for per-market telemetry service (bead asia.10.1).

Covers:
- Schema versioning (each payload tagged with SCHEMA_VERSION)
- Redis hot-path (gauge SET + counter INCR with TTL)
- PG event log emission (best-effort with no Redis or no DB)
- Read API (market_summary returns lag/age + counter rollup)
- Cleanup (SQL parameterized DELETE)
- Bucketization (completeness_bucket_for boundary checks)
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from app.services.telemetry.per_market_telemetry import (
    PerMarketTelemetry,
    _gauge_key,
)
from app.services.telemetry.schema import (
    COMPLETENESS_BUCKETS,
    SCHEMA_VERSION,
    MetricKey,
    benchmark_age_payload,
    completeness_bucket_for,
    completeness_distribution_payload,
    extraction_success_payload,
    freshness_lag_payload,
    opportunity_state_payload,
    universe_drift_payload,
)


# ---------------------------------------------------------------------------
# Schema payload builders
# ---------------------------------------------------------------------------
class TestSchemaPayloads:
    def test_freshness_lag_payload_versioned(self):
        p = freshness_lag_payload(
            last_refresh_at_epoch=1700000000.0, source="prices", symbols_refreshed=10,
        )
        assert p["schema_version"] == SCHEMA_VERSION
        assert p["last_refresh_at_epoch"] == 1700000000.0
        assert p["source"] == "prices"
        assert p["symbols_refreshed"] == 10

    def test_universe_drift_payload_handles_first_sync(self):
        p = universe_drift_payload(current_size=500, prior_size=None)
        assert p["delta"] == 0
        assert p["prior_size"] is None
        assert p["current_size"] == 500

    def test_universe_drift_payload_signed_delta(self):
        p = universe_drift_payload(current_size=480, prior_size=500)
        assert p["delta"] == -20

    def test_benchmark_age_payload(self):
        p = benchmark_age_payload(last_warmed_at_epoch=1700000001.0, benchmark_symbol="SPY")
        assert p["schema_version"] == SCHEMA_VERSION
        assert p["benchmark_symbol"] == "SPY"

    def test_extraction_payload_optional_fields_default_none(self):
        p = extraction_success_payload(language="en", success=True)
        assert p["latency_ms"] is None
        assert p["provider"] is None
        assert p["success"] is True

    def test_completeness_payload_normalizes_missing_buckets(self):
        p = completeness_distribution_payload(
            bucket_counts={"75-90": 5}, symbols_total=100,
        )
        # Every bucket appears with a count, even if zero.
        for b in COMPLETENESS_BUCKETS:
            assert b in p["bucket_counts"]
        assert p["bucket_counts"]["75-90"] == 5
        assert p["bucket_counts"]["0-25"] == 0

    # Catches accidental row-level or watchlist data entering the durable snapshot payload.
    def test_opportunity_payload_contains_only_aggregate_counts(self):
        payload = opportunity_state_payload(
            run_id=42,
            rows_total=100,
            survivor_count=12,
            action_state_counts={"setup_ready": 3, "data_limited": 4},
        )

        assert payload == {
            "schema_version": SCHEMA_VERSION,
            "run_id": 42,
            "rows_total": 100,
            "survivor_count": 12,
            "action_state_counts": {
                "exit_risk": 0,
                "deteriorating": 0,
                "event_risk": 0,
                "extended": 0,
                "data_limited": 4,
                "setup_ready": 3,
                "watch": 0,
            },
            "unknown_input_rate": pytest.approx(0.04),
        }
        serialized = json.dumps(payload).lower()
        for sensitive_key in ("symbol", "watchlist", "evidence"):
            assert sensitive_key not in serialized


class TestCompletenessBucketing:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0, "0-25"), (24, "0-25"), (25, "25-50"),
            (49, "25-50"), (50, "50-75"), (74, "50-75"),
            (75, "75-90"), (89, "75-90"), (90, "90-100"),
            (100, "90-100"),
        ],
    )
    def test_boundaries(self, score, expected):
        assert completeness_bucket_for(score) == expected


# ---------------------------------------------------------------------------
# Redis hot-path
# ---------------------------------------------------------------------------
class TestRedisHotPath:
    def _telemetry(self, redis_client):
        # session_factory raises so PG emits become no-ops; we only test Redis here.
        return PerMarketTelemetry(
            redis_client_factory=lambda: redis_client,
            session_factory=lambda: (_ for _ in ()).throw(RuntimeError("no DB in this test")),
        )

    def test_freshness_sets_gauge_with_ttl(self):
        client = MagicMock()
        telemetry = self._telemetry(client)
        telemetry.record_freshness("HK", source="prices", symbols_refreshed=42)

        client.set.assert_called_once()
        key, value = client.set.call_args.args
        assert key == _gauge_key(MetricKey.FRESHNESS_LAG, "HK")
        payload = json.loads(value)
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["symbols_refreshed"] == 42
        # TTL passed via ex= kwarg
        assert client.set.call_args.kwargs["ex"] == 15 * 86400

    def test_extraction_increments_per_language_counter(self):
        client = MagicMock()
        pipe = MagicMock()
        client.pipeline.return_value = pipe
        telemetry = self._telemetry(client)

        telemetry.record_extraction(
            None, language="ja", success=True, latency_ms=120, provider="litellm",
        )

        # Two pipeline.incr calls expected: one for "ja:total", one for "ja:success"
        # (ordering: total first then success when success=True).
        incr_keys = [c.args[0] for c in pipe.incr.call_args_list]
        assert any("ja:total" in k for k in incr_keys)
        assert any("ja:success" in k for k in incr_keys)
        assert pipe.expire.call_count == 2  # one per counter

    def test_extraction_failure_does_not_increment_success(self):
        client = MagicMock()
        pipe = MagicMock()
        client.pipeline.return_value = pipe
        telemetry = self._telemetry(client)

        telemetry.record_extraction(None, language="en", success=False)

        incr_keys = [c.args[0] for c in pipe.incr.call_args_list]
        assert any("en:total" in k for k in incr_keys)
        assert not any(":success" in k for k in incr_keys)

    def test_extraction_sanitizes_malformed_language(self):
        client = MagicMock()
        pipe = MagicMock()
        client.pipeline.return_value = pipe
        telemetry = self._telemetry(client)

        # Whitespace, colon, and over-long values must collapse to "unknown".
        telemetry.record_extraction(None, language="zh tw", success=True)
        telemetry.record_extraction(None, language="bad:tag", success=True)
        telemetry.record_extraction(None, language="x" * 32, success=True)

        all_incr_keys = [c.args[0] for c in pipe.incr.call_args_list]
        assert any(":unknown:total" in k for k in all_incr_keys)
        # No malformed dimension leaks into the key space.
        assert not any(" " in k for k in all_incr_keys)
        assert all("bad:tag" not in k for k in all_incr_keys)

    # Catches symbol/watchlist data being added to the Redis counter dimension.
    def test_opportunity_evidence_open_persists_only_the_surface_dimension(self):
        client = MagicMock()
        pipe = MagicMock()
        client.pipeline.return_value = pipe
        telemetry = self._telemetry(client)

        telemetry.record_opportunity_evidence_open("US", surface="watchlist")

        pipe.incr.assert_called_once()
        key = pipe.incr.call_args.args[0]
        assert ":opportunity_evidence_open:us:watchlist:" in key
        assert "symbol" not in key.lower()
        assert "nvda" not in key.lower()
        pipe.expire.assert_called_once()
        pipe.execute.assert_called_once()

    def test_records_silently_when_redis_unavailable(self):
        # No redis, no session — must never raise.
        telemetry = PerMarketTelemetry(
            redis_client_factory=lambda: None,
            session_factory=lambda: (_ for _ in ()).throw(RuntimeError("no DB")),
        )
        telemetry.record_freshness("US", source="prices", symbols_refreshed=1)
        telemetry.record_benchmark_age("US", benchmark_symbol="SPY")
        telemetry.record_universe_drift("HK", current_size=100, prior_size=90)
        telemetry.record_extraction(None, language="en", success=True)
        telemetry.record_completeness("HK", bucket_counts={"0-25": 1}, symbols_total=1)
        telemetry.record_opportunity_evidence_open("US", surface="scan")


# ---------------------------------------------------------------------------
# Opportunity-state DB aggregation
# ---------------------------------------------------------------------------
class TestOpportunityStateAggregation:
    # Catches per-row loading, nested-key reads, state omissions, and sensitive payload leakage.
    def test_aggregates_top_level_opportunity_keys_in_one_database_read(
        self, db_session
    ):
        from datetime import date

        from sqlalchemy import event

        from app.database import SessionLocal, engine
        from app.infra.db.models.feature_store import FeatureRun, StockFeatureDaily

        run = FeatureRun(
            as_of_date=date(2026, 8, 21),
            run_type="daily_snapshot",
            status="published",
        )
        db_session.add(run)
        db_session.flush()
        db_session.add_all(
            [
                StockFeatureDaily(
                    run_id=run.id,
                    symbol="ALPHA",
                    as_of_date=run.as_of_date,
                    details_json={
                        "correction_survivor": True,
                        "action_state": "setup_ready",
                        "opportunity_state": {"private": "must-not-leak"},
                    },
                ),
                StockFeatureDaily(
                    run_id=run.id,
                    symbol="BETA",
                    as_of_date=run.as_of_date,
                    details_json={
                        "correction_survivor": True,
                        "action_state": "data_limited",
                    },
                ),
                StockFeatureDaily(
                    run_id=run.id,
                    symbol="GAMMA",
                    as_of_date=run.as_of_date,
                    details_json={
                        "correction_survivor": False,
                        "action_state": "watch",
                    },
                ),
                StockFeatureDaily(
                    run_id=run.id,
                    symbol="LEGACY",
                    as_of_date=run.as_of_date,
                    details_json={},
                ),
            ]
        )
        db_session.commit()

        select_statements = []

        def capture_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "stock_feature_daily" in statement:
                select_statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture_select)
        client = MagicMock()
        try:
            telemetry = PerMarketTelemetry(
                redis_client_factory=lambda: client,
                session_factory=SessionLocal,
            )
            emit_pg = MagicMock()
            telemetry._emit_pg = emit_pg
            telemetry.record_opportunity_state_from_db("US", run.id)
        finally:
            event.remove(engine, "before_cursor_execute", capture_select)

        assert len(select_statements) == 1
        client.set.assert_called_once()
        gauge_payload = json.loads(client.set.call_args.args[1])
        assert gauge_payload["run_id"] == run.id
        assert gauge_payload["rows_total"] == 4
        assert gauge_payload["survivor_count"] == 2
        assert gauge_payload["action_state_counts"] == {
            "exit_risk": 0,
            "deteriorating": 0,
            "event_risk": 0,
            "extended": 0,
            "data_limited": 1,
            "setup_ready": 1,
            "watch": 1,
        }
        assert gauge_payload["unknown_input_rate"] == pytest.approx(0.25)

        emit_pg.assert_called_once()
        assert emit_pg.call_args.kwargs["market"] == "US"
        assert emit_pg.call_args.kwargs["metric_key"] == MetricKey.OPPORTUNITY_STATE
        event_payload = emit_pg.call_args.kwargs["payload"]
        assert event_payload == gauge_payload
        serialized = json.dumps(event_payload).lower()
        for sensitive_value in (
            "symbol",
            "watchlist",
            "opportunity_state",
            "alpha",
            "beta",
            "gamma",
            "legacy",
            "must-not-leak",
        ):
            assert sensitive_value not in serialized

    # Catches observability failures escaping into the publication path.
    def test_opportunity_database_aggregation_is_best_effort(self):
        summary_reader = MagicMock()
        summary_reader.for_feature_run.side_effect = RuntimeError(
            "database unavailable"
        )
        telemetry = PerMarketTelemetry(
            redis_client_factory=lambda: None,
            opportunity_summary_reader=summary_reader,
        )

        assert telemetry.record_opportunity_state_from_db("US", 42) is None
        summary_reader.for_feature_run.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# Read API — market_summary derives lag from stored timestamp
# ---------------------------------------------------------------------------
class TestMarketSummary:
    def _telemetry(self, client):
        return PerMarketTelemetry(
            redis_client_factory=lambda: client,
            session_factory=lambda: (_ for _ in ()).throw(RuntimeError("no DB")),
        )

    def test_freshness_lag_derived_from_timestamp(self):
        client = MagicMock()
        # Pre-load gauge: refresh happened 30 seconds ago.
        ts = time.time() - 30
        gauge_payload = freshness_lag_payload(
            last_refresh_at_epoch=ts, source="prices", symbols_refreshed=5,
        )

        # market_summary uses MGET in fixed order matching _SUMMARY_GAUGE_KEYS:
        # freshness, drift, benchmark, completeness.
        def mget_side_effect(keys):
            return [
                json.dumps(gauge_payload) if k == _gauge_key(MetricKey.FRESHNESS_LAG, "HK") else None
                for k in keys
            ]

        client.mget.side_effect = mget_side_effect
        client.scan_iter.return_value = iter([])
        telemetry = self._telemetry(client)

        summary = telemetry.market_summary("HK")
        assert summary["market"] == "HK"
        # Single MGET round-trip for all gauges, not per-key GETs.
        client.mget.assert_called_once()
        lag = summary[MetricKey.FRESHNESS_LAG]["lag_seconds"]
        assert 25 <= lag <= 35  # ~30s, allow a bit of slack

    def test_market_summary_handles_empty_redis(self):
        client = MagicMock()
        client.mget.return_value = [None, None, None, None, None, None]
        client.scan_iter.return_value = iter([])
        telemetry = self._telemetry(client)

        summary = telemetry.market_summary("US")
        assert summary["market"] == "US"
        assert summary[MetricKey.FRESHNESS_LAG] is None
        assert summary[MetricKey.BENCHMARK_AGE] is None
        assert summary["extraction_today"] == {"by_language": {}}

    def test_extraction_counters_visible_under_every_market_summary(self):
        """Round-trip: extraction is recorded under SHARED, but per-market
        summaries must surface those counters (extraction has no per-market
        dimension). Regression test for the cross-scope read bug.
        """
        client = MagicMock()
        # Gauges all empty; we only care about the extraction scan/mget path.
        client.mget.return_value = [None, None, None, None, None, None]

        # The scan_iter pattern under inspection — must scan SHARED scope,
        # not the per-market scope, so capture the actual pattern.
        scanned_patterns: list = []

        def scan_iter_side_effect(match):
            scanned_patterns.append(match)
            return iter(["telemetry:counter:extraction_success:shared:en:total:20260101"])

        client.scan_iter.side_effect = scan_iter_side_effect

        # mget for counters returns a single value matching the one scanned key.
        # Note: client.mget is called twice in market_summary (gauges + counters);
        # use side_effect to handle both.
        original_mget = client.mget.return_value

        def mget_side_effect(keys):
            if keys == ["telemetry:counter:extraction_success:shared:en:total:20260101"]:
                return [b"42"]
            return original_mget

        client.mget.side_effect = mget_side_effect

        telemetry = self._telemetry(client)
        summary = telemetry.market_summary("HK")

        assert any("shared" in p for p in scanned_patterns), (
            f"market_summary('HK') must scan the SHARED scope for extraction "
            f"counters, but scanned: {scanned_patterns}"
        )
        assert summary["extraction_today"] == {"by_language": {"en": {"total": 42}}}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
class TestCleanup:
    def test_cleanup_deletes_via_orm_with_cutoff(self):
        from datetime import datetime, timedelta, timezone

        from sqlalchemy.sql.elements import BinaryExpression

        delete_query = MagicMock()
        delete_query.delete.return_value = 7
        filter_query = MagicMock()
        filter_query.filter.return_value = delete_query
        db = MagicMock()
        db.query.return_value = filter_query

        telemetry = PerMarketTelemetry(
            redis_client_factory=lambda: None,
            session_factory=lambda: db,
        )
        before = datetime.now(timezone.utc)
        deleted = telemetry.cleanup_old_events(retention_days=15)
        after = datetime.now(timezone.utc)

        assert deleted == 7
        # Validate the cutoff is in the past by ~15 days, not in the future
        # (catches sign-flip regressions like `now + timedelta(days=...)`).
        filter_call = filter_query.filter.call_args
        expr = filter_call.args[0]
        assert isinstance(expr, BinaryExpression)
        cutoff = expr.right.value
        assert before - timedelta(days=15, seconds=5) <= cutoff <= after - timedelta(days=15, seconds=-5)

        delete_query.delete.assert_called_once_with(synchronize_session=False)
        db.commit.assert_called_once()
        db.close.assert_called_once()

    def test_cleanup_returns_zero_on_failure(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("PG down")
        telemetry = PerMarketTelemetry(
            redis_client_factory=lambda: None,
            session_factory=lambda: db,
        )
        assert telemetry.cleanup_old_events() == 0
        db.rollback.assert_called_once()
