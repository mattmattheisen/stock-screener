"""Single persistence mapping for canonical breadth results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from sqlalchemy.orm import Session

from app.models.breadth_contributor import (
    MarketBreadthContributor,
    MarketBreadthContributorSnapshot,
)
from app.models.market_breadth import MarketBreadth

from .contributors import (
    BREADTH_CONTRIBUTOR_SIGNALS,
    CONTRIBUTOR_RETENTION_SESSIONS,
    reconcile_contributor_counts,
)
from .types import (
    CURRENT_BREADTH_CALCULATION_REVISION,
    BreadthContributorSnapshotResult,
    BreadthDailyResult,
)


class BreadthPersistence:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _assign(
        record: MarketBreadth,
        result: BreadthDailyResult,
        *,
        duration_seconds: float | None,
    ) -> None:
        values = result.to_record_mapping()
        if result.calculation_revision != CURRENT_BREADTH_CALCULATION_REVISION:
            raise ValueError("Only current revision breadth results may be persisted")
        for column in MarketBreadth.__table__.columns:
            if column.name in {"id", "created_at", "calculation_duration_seconds"}:
                continue
            if column.name in values:
                setattr(record, column.name, values[column.name])
        record.total_stocks_scanned = result.broad_universe_count
        record.calculation_revision = CURRENT_BREADTH_CALCULATION_REVISION
        record.calculation_duration_seconds = duration_seconds

    def _upsert_without_commit(
        self,
        result: BreadthDailyResult,
        *,
        duration_seconds: float | None,
    ) -> MarketBreadth:
        record = (
            self._db.query(MarketBreadth)
            .filter(
                MarketBreadth.market == result.market,
                MarketBreadth.date == result.calculation_date,
            )
            .first()
        )
        if record is None:
            record = MarketBreadth(
                market=result.market,
                date=result.calculation_date,
                stocks_up_4pct=0,
                stocks_down_4pct=0,
                stocks_up_25pct_quarter=0,
                stocks_down_25pct_quarter=0,
                stocks_up_25pct_month=0,
                stocks_down_25pct_month=0,
                stocks_up_50pct_month=0,
                stocks_down_50pct_month=0,
                stocks_up_13pct_34days=0,
                stocks_down_13pct_34days=0,
                total_stocks_scanned=0,
            )
            self._db.add(record)
        self._assign(record, result, duration_seconds=duration_seconds)
        return record

    def upsert_daily(
        self,
        result: BreadthDailyResult,
        *,
        contributor_snapshot: BreadthContributorSnapshotResult | None = None,
        duration_seconds: float | None,
    ) -> MarketBreadth:
        if contributor_snapshot is not None:
            reconcile_contributor_counts(contributor_snapshot, result)
        try:
            record = self._upsert_without_commit(
                result,
                duration_seconds=duration_seconds,
            )
            self._db.flush()
            if contributor_snapshot is not None:
                self._replace_snapshot_without_commit(contributor_snapshot)
            else:
                self._delete_snapshot_without_commit(
                    result.market,
                    result.calculation_date,
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        if contributor_snapshot is not None:
            self._prune_market(contributor_snapshot.market)
        return record

    def upsert_many(
        self,
        results: Iterable[BreadthDailyResult],
        *,
        contributor_snapshots_by_date: Mapping[
            date, BreadthContributorSnapshotResult
        ] | None = None,
        duration_seconds_by_date: Mapping[date, float] | None = None,
    ) -> tuple[MarketBreadth, ...]:
        ordered_results = tuple(results)
        if contributor_snapshots_by_date is not None:
            expected_dates = {result.calculation_date for result in ordered_results}
            if set(contributor_snapshots_by_date) != expected_dates:
                raise ValueError(
                    "Contributor snapshot dates must match breadth result dates"
                )
            for result in ordered_results:
                reconcile_contributor_counts(
                    contributor_snapshots_by_date[result.calculation_date],
                    result,
                )
        try:
            records = tuple(
                self._upsert_without_commit(
                    result,
                    duration_seconds=(
                        duration_seconds_by_date.get(result.calculation_date)
                        if duration_seconds_by_date is not None
                        else None
                    ),
                )
                for result in ordered_results
            )
            self._db.flush()
            if contributor_snapshots_by_date is not None:
                for result in ordered_results:
                    self._replace_snapshot_without_commit(
                        contributor_snapshots_by_date[result.calculation_date]
                    )
            else:
                for result in ordered_results:
                    self._delete_snapshot_without_commit(
                        result.market,
                        result.calculation_date,
                    )
            if records:
                self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        if contributor_snapshots_by_date is not None:
            for market in sorted(
                {snapshot.market for snapshot in contributor_snapshots_by_date.values()}
            ):
                self._prune_market(market)
        return records

    def replace_contributor_snapshots(
        self,
        snapshots: Iterable[BreadthContributorSnapshotResult],
        *,
        expected_aggregates: Mapping[date, BreadthDailyResult],
    ) -> tuple[MarketBreadthContributorSnapshot, ...]:
        """Atomically replace snapshots without mutating aggregate rows."""
        ordered_snapshots = tuple(
            sorted(snapshots, key=lambda item: item.calculation_date)
        )
        if not ordered_snapshots:
            return ()
        if {item.calculation_date for item in ordered_snapshots} != set(
            expected_aggregates
        ):
            raise ValueError(
                "Expected aggregate dates must match contributor snapshot dates"
            )
        markets = {item.market for item in ordered_snapshots}
        if len(markets) != 1:
            raise ValueError("Contributor-only replacement must target one market")

        for snapshot in ordered_snapshots:
            expected = expected_aggregates[snapshot.calculation_date]
            reconcile_contributor_counts(snapshot, expected)
            stored = (
                self._db.query(MarketBreadth)
                .filter(
                    MarketBreadth.market == snapshot.market,
                    MarketBreadth.date == snapshot.calculation_date,
                )
                .one_or_none()
            )
            if stored is None:
                raise ValueError(
                    "Missing aggregate breadth row for contributor snapshot "
                    f"{snapshot.market}/{snapshot.calculation_date.isoformat()}"
                )
            if stored.calculation_revision != expected.calculation_revision:
                raise ValueError("Stored aggregate calculation revision mismatch")
            for definition in BREADTH_CONTRIBUTOR_SIGNALS.values():
                if getattr(stored, definition.aggregate_field) != getattr(
                    expected.values,
                    definition.aggregate_field,
                ):
                    aggregate_count = getattr(stored, definition.aggregate_field)
                    contributor_count = getattr(
                        expected.values,
                        definition.aggregate_field,
                    )
                    raise ValueError(
                        f"{snapshot.market},"
                        f"{snapshot.calculation_date.isoformat()},"
                        f"{definition.aggregate_field},"
                        f"{aggregate_count},{contributor_count}"
                    )

        try:
            records = tuple(
                self._replace_snapshot_without_commit(snapshot)
                for snapshot in ordered_snapshots
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        self._prune_market(next(iter(markets)))
        return records

    def _replace_snapshot_without_commit(
        self,
        snapshot: BreadthContributorSnapshotResult,
    ) -> MarketBreadthContributorSnapshot:
        self._delete_snapshot_without_commit(
            snapshot.market,
            snapshot.calculation_date,
        )

        record = MarketBreadthContributorSnapshot(
            market=snapshot.market,
            date=snapshot.calculation_date,
            calculation_revision=snapshot.calculation_revision,
            schema_id=snapshot.schema_id,
        )
        record.contributors = [
            MarketBreadthContributor(
                symbol=contributor.symbol,
                company_name=contributor.company_name,
                ibd_industry_group=contributor.ibd_industry_group,
                daily_change_pct=contributor.daily_change_pct,
                signals_json=dict(contributor.signals),
            )
            for contributor in snapshot.contributors
        ]
        self._db.add(record)
        self._db.flush()
        return record

    def _delete_snapshot_without_commit(
        self,
        market: str,
        calculation_date: date,
    ) -> None:
        existing = (
            self._db.query(MarketBreadthContributorSnapshot)
            .filter(
                MarketBreadthContributorSnapshot.market == market,
                MarketBreadthContributorSnapshot.date == calculation_date,
            )
            .one_or_none()
        )
        if existing is not None:
            self._db.delete(existing)
            self._db.flush()

    def _prune_market(self, market: str) -> None:
        stale = (
            self._db.query(MarketBreadthContributorSnapshot)
            .filter(MarketBreadthContributorSnapshot.market == market)
            .order_by(MarketBreadthContributorSnapshot.date.desc())
            .offset(CONTRIBUTOR_RETENTION_SESSIONS)
            .all()
        )
        if not stale:
            return
        try:
            for record in stale:
                self._db.delete(record)
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
