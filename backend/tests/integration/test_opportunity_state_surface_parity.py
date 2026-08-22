"""Cross-surface release contract for Correction Survivors and Action State."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "opportunity_state_snapshot.py"
)

EXPECTED_STATES = {
    "EXIT": "exit_risk",
    "DETERIORATING": "deteriorating",
    "EVENT": "event_risk",
    "EXTENDED": "extended",
    "LIMITED": "data_limited",
    "READY": "setup_ready",
    "WATCH": "watch",
    "LEGACY": None,
}

EXPECTED_SURVIVOR_ORDER = [
    "READY",
    "EVENT",
    "DETERIORATING",
    "EXTENDED",
    "WATCH",
]

EXPECTED_PILLARS = {
    "EXIT": {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 17.0,
        "trend_integrity": 16.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    },
    "DETERIORATING": {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 15.0,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    },
    "EVENT": {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 16.6,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    },
    "EXTENDED": {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 15.0,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    },
    "LIMITED": {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 17.0,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    },
    "READY": {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 17.0,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    },
    "WATCH": {
        "benchmark_leadership": 20.0,
        "multi_horizon_rs": 15.0,
        "trend_integrity": 20.0,
        "structure_tightness": 20.0,
        "liquidity_freshness": 20.0,
    },
}

EXPECTED_WARNINGS = {
    "EXIT": [],
    "DETERIORATING": [],
    "EVENT": ["benchmark_date_lag"],
    "EXTENDED": [],
    "LIMITED": [],
    "READY": [],
    "WATCH": [],
}

EXPECTED_REASONS = {
    "EXIT": ["hard_invalidation:breaks_50d_support"],
    "DETERIORATING": ["deterioration_confirmed"],
    "EVENT": ["earnings_soon"],
    "EXTENDED": ["extended"],
    "LIMITED": ["required_evidence"],
    "READY": ["setup_ready"],
    "WATCH": ["watch"],
}


def _load_fixture_module():
    if not FIXTURE_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        "opportunity_state_snapshot_fixture",
        FIXTURE_PATH,
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def parity_snapshot(tmp_path_factory):
    module = _load_fixture_module()
    if module is None:
        yield None
        return
    snapshot = module.build_parity_snapshot(
        tmp_path_factory.mktemp("opportunity-state-parity") / "snapshot.db"
    )
    try:
        yield snapshot
    finally:
        snapshot.close()


def _compact_projection(rows):
    return {
        row["symbol"]: {
            "correction_survivor": row["correction_survivor"],
            "resilience_score": row["resilience_score"],
            "action_state": row["action_state"],
            "opportunity_state": row["opportunity_state"],
        }
        for row in rows
    }


def test_live_and_static_contracts_match_for_all_action_states(
    tmp_path,
    parity_snapshot,
):
    """Break caught: either surface drifts from the persisted compact contract."""
    assert parity_snapshot is not None, (
        "deterministic fixture backend/tests/fixtures/"
        "opportunity_state_snapshot.py is missing"
    )

    live_rows = parity_snapshot.query_live_rows()
    static_rows = parity_snapshot.export_and_read_static_rows(tmp_path)
    static_manifest = parity_snapshot.read_static_manifest(tmp_path)

    assert _compact_projection(live_rows) == _compact_projection(static_rows)
    assert {row["symbol"]: row["action_state"] for row in live_rows} == EXPECTED_STATES
    assert parity_snapshot.query_live_survivor_symbols() == EXPECTED_SURVIVOR_ORDER
    assert parity_snapshot.static_survivor_symbols(
        static_rows,
        static_manifest,
    ) == EXPECTED_SURVIVOR_ORDER

    rows_by_symbol = {row["symbol"]: row for row in static_rows}
    for symbol, expected_pillars in EXPECTED_PILLARS.items():
        evidence = rows_by_symbol[symbol]["opportunity_state"]
        assert evidence["score_pillars"] == expected_pillars
        assert evidence["warnings"] == EXPECTED_WARNINGS[symbol]
        assert evidence["action_reasons"] == EXPECTED_REASONS[symbol]
        assert evidence["schema_version"] == 1
        assert evidence["policy_version"] == "correction-survivors-v1"
        assert evidence["as_of_date"] == "2026-08-21"
        assert evidence["market"] == "US"
        assert evidence["mic"] == "XNAS"
        assert evidence["benchmark_symbol"] == "SPY"
        assert evidence["benchmark_as_of_date"] == (
            "2026-08-20" if symbol == "EVENT" else "2026-08-21"
        )

    assert rows_by_symbol["LEGACY"]["correction_survivor"] is None
    assert rows_by_symbol["LEGACY"]["resilience_score"] is None
    assert rows_by_symbol["LEGACY"]["action_state"] is None
    assert rows_by_symbol["LEGACY"]["opportunity_state"] is None
    assert "se_explain" not in rows_by_symbol["READY"]
    assert "se_candidates" not in rows_by_symbol["READY"]

    assert static_manifest["schema_version"] == "static-scan-v2"
    assert static_manifest["features"] == {"opportunity_state": True}
    survivor_screen = next(
        screen
        for screen in static_manifest["preset_screens"]
        if screen["id"] == "correction_survivors"
    )
    assert survivor_screen["filters"] == {"correctionSurvivor": True}
    assert survivor_screen["sort_by"] == "resilience_score"
    assert survivor_screen["sort_order"] == "desc"
