"""Contract tests for shared persisted opportunity-state aggregation."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base
from app.domain.scanning.opportunity_state import ActionState
from app.infra.db.repositories.opportunity_summary_repo import (
    SqlOpportunityStateSummaryRepository,
)
from app.models.scan_result import Scan, ScanResult


def test_scan_summary_aggregates_all_counts_in_one_query():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Scan(scan_id="scan-summary", status="completed"))
        session.add_all(
            [
                ScanResult(
                    scan_id="scan-summary",
                    symbol="READY",
                    details={
                        "correction_survivor": True,
                        "action_state": "setup_ready",
                    },
                ),
                ScanResult(
                    scan_id="scan-summary",
                    symbol="WATCH",
                    details={
                        "correction_survivor": True,
                        "action_state": "watch",
                    },
                ),
                ScanResult(
                    scan_id="scan-summary",
                    symbol="NOT-SURVIVOR",
                    details={
                        "correction_survivor": False,
                        "action_state": "watch",
                    },
                ),
                ScanResult(
                    scan_id="scan-summary",
                    symbol="LEGACY",
                    details={},
                ),
            ]
        )
        session.commit()

        statements = []

        def capture(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            summary = SqlOpportunityStateSummaryRepository(session).for_scan(
                "scan-summary"
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert summary.rows_total == 4
    assert summary.survivor_count == 2
    assert summary.action_state_counts[ActionState.SETUP_READY] == 1
    assert summary.action_state_counts[ActionState.WATCH] == 2
    assert summary.survivor_action_state_counts[ActionState.SETUP_READY] == 1
    assert summary.survivor_action_state_counts[ActionState.WATCH] == 1
    assert all(
        summary.action_state_counts[state] == 0
        for state in ActionState
        if state not in {ActionState.SETUP_READY, ActionState.WATCH}
    )
