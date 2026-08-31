"""Persistence for immutable CAN SLIM V1-vs-V2 shadow evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.canslim_v2_shadow import CANSLIMV2ShadowComparison


class ShadowEvidenceConflictError(RuntimeError):
    """The same point-in-time identity produced different shadow evidence."""


def _canonical_evidence(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    payload = dict(evidence)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return payload, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(evidence: Mapping[str, Any], field: str) -> str:
    value = evidence.get(field)
    if value is None:
        raise ValueError(f"{field} is required for persisted shadow evidence")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} is required for persisted shadow evidence")
    return normalized


def _parse_as_of_date(evidence: Mapping[str, Any]) -> date:
    raw = _required_text(evidence, "as_of_date")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("as_of_date must be an ISO calendar date") from exc


class SqlCANSLIMV2ShadowRepository:
    """Store one immutable evidence row per same-snapshot comparison identity."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, evidence: Mapping[str, Any]) -> tuple[CANSLIMV2ShadowComparison, bool]:
        payload, evidence_hash = _canonical_evidence(evidence)
        as_of_date = _parse_as_of_date(payload)
        run_ref = _required_text(payload, "run_ref")
        symbol = _required_text(payload, "symbol").upper()
        methodology_version = _required_text(payload, "methodology_version")

        existing = self._find(
            as_of_date=as_of_date,
            run_ref=run_ref,
            symbol=symbol,
            methodology_version=methodology_version,
        )
        if existing is not None:
            self._assert_same_evidence(existing, evidence_hash)
            return existing, False

        row = CANSLIMV2ShadowComparison(
            as_of_date=as_of_date,
            run_ref=run_ref,
            symbol=symbol,
            methodology_version=methodology_version,
            v1_score=float(payload["v1_score"]),
            v1_passes=bool(payload["v1_passes"]),
            v1_rating=str(payload["v1_rating"]),
            v2_stock_score=float(payload["v2_stock_score"]),
            v2_stock_passes=bool(payload["v2_stock_passes"]),
            v2_market_passes=bool(payload["v2_market_passes"]),
            v2_actionable=bool(payload["v2_actionable"]),
            v2_rating=str(payload["v2_rating"]),
            v2_status=str(payload["v2_status"]),
            market_exposure_score=(
                float(payload["market_exposure_score"])
                if payload.get("market_exposure_score") is not None
                else None
            ),
            market_stance=(
                str(payload["market_stance"])
                if payload.get("market_stance") is not None
                else None
            ),
            score_delta_v2_minus_v1=float(payload["score_delta_v2_minus_v1"]),
            action_disagreement=bool(payload["action_disagreement"]),
            evidence_hash=evidence_hash,
            evidence_json=payload,
        )

        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            concurrent = self._find(
                as_of_date=as_of_date,
                run_ref=run_ref,
                symbol=symbol,
                methodology_version=methodology_version,
            )
            if concurrent is None:
                raise
            self._assert_same_evidence(concurrent, evidence_hash)
            return concurrent, False

        return row, True

    def _find(
        self,
        *,
        as_of_date: date,
        run_ref: str,
        symbol: str,
        methodology_version: str,
    ) -> CANSLIMV2ShadowComparison | None:
        return (
            self._session.query(CANSLIMV2ShadowComparison)
            .filter(
                CANSLIMV2ShadowComparison.as_of_date == as_of_date,
                CANSLIMV2ShadowComparison.run_ref == run_ref,
                CANSLIMV2ShadowComparison.symbol == symbol,
                CANSLIMV2ShadowComparison.methodology_version == methodology_version,
            )
            .one_or_none()
        )

    @staticmethod
    def _assert_same_evidence(
        existing: CANSLIMV2ShadowComparison,
        evidence_hash: str,
    ) -> None:
        if existing.evidence_hash != evidence_hash:
            raise ShadowEvidenceConflictError(
                "shadow evidence drift detected for an existing point-in-time identity"
            )
