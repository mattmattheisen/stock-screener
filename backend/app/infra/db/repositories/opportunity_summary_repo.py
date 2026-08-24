"""SQL aggregate readers for persisted opportunity-state projections."""

from __future__ import annotations

from sqlalchemy import case, func
from sqlalchemy.orm import Session, sessionmaker

from app.domain.scanning.opportunity_state import ActionState
from app.domain.scanning.opportunity_summary import OpportunityStateSummary
from app.infra.db.models.feature_store import StockFeatureDaily
from app.models.scan_result import ScanResult


class SqlOpportunityStateSummaryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def for_scan(self, scan_id: str) -> OpportunityStateSummary:
        return self._aggregate(
            model=ScanResult,
            details=ScanResult.details,
            predicate=ScanResult.scan_id == scan_id,
        )

    def for_feature_run(self, run_id: int) -> OpportunityStateSummary:
        return self._aggregate(
            model=StockFeatureDaily,
            details=StockFeatureDaily.details_json,
            predicate=StockFeatureDaily.run_id == int(run_id),
        )

    def _aggregate(self, *, model, details, predicate) -> OpportunityStateSummary:
        action_state = details["action_state"].as_string()
        survivor = details["correction_survivor"].as_boolean()
        aggregates = [
            func.count().label("rows_total"),
            func.coalesce(
                func.sum(case((survivor.is_(True), 1), else_=0)),
                0,
            ).label("survivor_count"),
        ]
        aggregates.extend(
            func.coalesce(
                func.sum(case((action_state == state.value, 1), else_=0)),
                0,
            ).label(f"state_{state.value}")
            for state in ActionState
        )
        aggregates.extend(
            func.coalesce(
                func.sum(
                    case(
                        (
                            survivor.is_(True) & (action_state == state.value),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label(f"survivor_state_{state.value}")
            for state in ActionState
        )
        row = (
            self._session.query(*aggregates).select_from(model).filter(predicate).one()
        )
        state_count = len(ActionState)
        return OpportunityStateSummary(
            rows_total=int(row[0] or 0),
            survivor_count=int(row[1] or 0),
            action_state_counts={
                state: int(row[index + 2] or 0)
                for index, state in enumerate(ActionState)
            },
            survivor_action_state_counts={
                state: int(row[index + 2 + state_count] or 0)
                for index, state in enumerate(ActionState)
            },
        )


class SessionOpportunityStateSummaryReader:
    """Own a short-lived session for telemetry and other service consumers."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def for_scan(self, scan_id: str) -> OpportunityStateSummary:
        with self._session_factory() as session:
            return SqlOpportunityStateSummaryRepository(session).for_scan(scan_id)

    def for_feature_run(self, run_id: int) -> OpportunityStateSummary:
        with self._session_factory() as session:
            return SqlOpportunityStateSummaryRepository(session).for_feature_run(run_id)
