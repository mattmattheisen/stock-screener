"""Contributor-only breadth snapshot backfill orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.market_breadth import MarketBreadth

from .breadth.query import breadth_query
from .breadth_backfill import BreadthBackfillExecutor, BreadthBackfillPlan
from .derived_data_execution_policy import (
    DerivedDataExecutionMode,
    DerivedDataExecutionPolicy,
    DerivedDataTargetKind,
)

if TYPE_CHECKING:
    from .breadth_calculator_service import BreadthCalculatorService


class BreadthContributorBackfillService:
    """Regenerate retained snapshots without changing aggregate breadth rows."""

    def __init__(
        self,
        db: Session,
        *,
        calculator: BreadthCalculatorService,
        executor: BreadthBackfillExecutor | None = None,
    ) -> None:
        self._db = db
        self._calculator = calculator
        self._executor = executor or BreadthBackfillExecutor(calculator)

    def run(self, *, limit: int = 20) -> dict[str, int | str]:
        if limit < 1:
            raise ValueError("Contributor backfill limit must be positive")
        market = self._calculator.market.upper()
        newest_rows = (
            breadth_query(self._db, market=market)
            .with_entities(
                MarketBreadth.date,
                MarketBreadth.contributor_calculation_signature,
            )
            .order_by(MarketBreadth.date.desc())
            .limit(limit)
            .all()
        )
        if not newest_rows:
            return {
                "market": market,
                "requested_dates": 0,
                "committed_dates": 0,
            }
        newest_dates = [
            row.date
            for row in newest_rows
            if row.contributor_calculation_signature is not None
        ]
        skipped_unverifiable_dates = len(newest_rows) - len(newest_dates)
        if not newest_dates:
            return {
                "market": market,
                "requested_dates": len(newest_rows),
                "committed_dates": 0,
                "skipped_unverifiable_dates": skipped_unverifiable_dates,
            }

        policy = DerivedDataExecutionPolicy(
            mode=DerivedDataExecutionMode.STRICT_CACHE_ONLY,
            target_kind=DerivedDataTargetKind.HISTORICAL,
        )
        result = self._executor.execute(
            BreadthBackfillPlan(dates=tuple(sorted(newest_dates))),
            policy=policy,
            require_complete_cache_coverage=True,
            contributor_only=True,
        ).to_legacy_dict()
        report: dict[str, int | str] = {
            "market": market,
            "requested_dates": len(newest_rows),
            "committed_dates": int(result["processed"]),
        }
        if skipped_unverifiable_dates:
            report["skipped_unverifiable_dates"] = skipped_unverifiable_dates
        return report
