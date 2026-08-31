"""Repository tests for immutable CAN SLIM V1-vs-V2 shadow evidence."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.infra.db.repositories.canslim_v2_shadow_repo import (
    ShadowEvidenceConflictError,
    SqlCANSLIMV2ShadowRepository,
)
from app.models.canslim_v2_shadow import CANSLIMV2ShadowComparison
from app.scanners.canslim_v2_shadow import CANSLIMV2ShadowRecord


def _record(**overrides) -> CANSLIMV2ShadowRecord:
    values = {
        "symbol": "NVDA",
        "as_of_date": "2026-08-31",
        "run_ref": "feature-run:123",
        "methodology_version": "canslim_v2",
        "v1_score": 76.0,
        "v1_passes": True,
        "v1_rating": "Buy",
        "v2_stock_score": 84.0,
        "v2_stock_passes": True,
        "v2_market_passes": True,
        "v2_actionable": True,
        "v2_rating": "Buy",
        "v2_status": "qualified",
        "market_exposure_score": 72.0,
        "market_stance": "Confirmed Uptrend",
        "score_delta_v2_minus_v1": 8.0,
        "action_disagreement": False,
        "criteria": {
            letter: {
                "letter": letter,
                "score": 10.0 if letter != "M" else 0.0,
                "max_points": 0.0 if letter == "M" else 20.0,
                "passes": True,
            }
            for letter in "CANSLIM"
        },
    }
    values.update(overrides)
    return CANSLIMV2ShadowRecord(**values)


def test_save_is_idempotent_for_identical_same_snapshot_evidence(session: Session):
    repo = SqlCANSLIMV2ShadowRepository(session)
    payload = _record().as_dict()

    first, first_created = repo.save(payload)
    second, second_created = repo.save(payload)

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert session.query(CANSLIMV2ShadowComparison).count() == 1
    assert first.symbol == "NVDA"
    assert first.run_ref == "feature-run:123"
    assert first.evidence_json["criteria"]["M"]["max_points"] == 0.0
    assert len(first.evidence_hash) == 64


def test_save_rejects_evidence_drift_for_existing_identity(session: Session):
    repo = SqlCANSLIMV2ShadowRepository(session)
    repo.save(_record().as_dict())

    drifted = _record(v1_score=77.0).as_dict()
    with pytest.raises(ShadowEvidenceConflictError, match="drift"):
        repo.save(drifted)

    assert session.query(CANSLIMV2ShadowComparison).count() == 1


def test_save_requires_point_in_time_identity(session: Session):
    repo = SqlCANSLIMV2ShadowRepository(session)

    missing_run = _record(run_ref=None).as_dict()
    with pytest.raises(ValueError, match="run_ref"):
        repo.save(missing_run)

    missing_date = _record(as_of_date=None).as_dict()
    with pytest.raises(ValueError, match="as_of_date"):
        repo.save(missing_date)


def test_save_normalizes_symbol_identity_before_hashing(session: Session):
    repo = SqlCANSLIMV2ShadowRepository(session)

    first, first_created = repo.save(_record(symbol="nvda").as_dict())
    second, second_created = repo.save(_record(symbol="NVDA").as_dict())

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert first.symbol == "NVDA"
    assert first.evidence_json["symbol"] == "NVDA"
    assert session.query(CANSLIMV2ShadowComparison).count() == 1
