"""Validated read model for persisted breadth contributor snapshots."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session, joinedload

from app.models.breadth_contributor import (
    MarketBreadthContributorSnapshot,
)
from app.models.market_breadth import MarketBreadth

from .contributors import (
    BREADTH_CONTRIBUTOR_SIGNALS,
    CONTRIBUTOR_SCHEMA_ID,
    BreadthContributorContractError,
    parse_contributor_rows,
    reconcile_contributor_aggregate,
)
from .types import CURRENT_BREADTH_CALCULATION_REVISION

logger = logging.getLogger(__name__)


class BreadthContributorSnapshotUnavailable(LookupError):
    """No persisted contributor snapshot exists for the requested market/date."""


class BreadthContributorSnapshotInconsistent(ValueError):
    """A persisted contributor snapshot fails its canonical contract."""


@dataclass(frozen=True, slots=True)
class BreadthContributorItemPayload:
    symbol: str
    company_name: str | None
    ibd_industry_group: str
    daily_change_pct: float | None
    signals: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class BreadthContributorDocumentPayload:
    schema: str
    market: str
    date: date
    calculation_revision: int
    contributors: tuple[BreadthContributorItemPayload, ...]


@dataclass(frozen=True, slots=True)
class BreadthContributorIndexPayload:
    schema: str
    market: str
    calculation_revision: int
    dates: tuple[date, ...]


def _load_snapshot(
    db: Session,
    market: str,
    calculation_date: date,
) -> MarketBreadthContributorSnapshot:
    normalized_market = market.upper()
    snapshot = (
        db.query(MarketBreadthContributorSnapshot)
        .options(joinedload(MarketBreadthContributorSnapshot.contributors))
        .filter(
            MarketBreadthContributorSnapshot.market == normalized_market,
            MarketBreadthContributorSnapshot.date == calculation_date,
        )
        .one_or_none()
    )
    if snapshot is None:
        raise BreadthContributorSnapshotUnavailable(
            f"No breadth contributors for {normalized_market}/{calculation_date}"
        )
    return snapshot


def _document_from_snapshot(
    db: Session,
    snapshot: MarketBreadthContributorSnapshot,
) -> BreadthContributorDocumentPayload:
    if snapshot.schema_id != CONTRIBUTOR_SCHEMA_ID:
        raise BreadthContributorSnapshotInconsistent(
            f"Unsupported contributor schema {snapshot.schema_id!r}"
        )
    if snapshot.calculation_revision != CURRENT_BREADTH_CALCULATION_REVISION:
        raise BreadthContributorSnapshotInconsistent(
            "Contributor calculation revision is not current"
        )
    aggregate = (
        db.query(MarketBreadth)
        .filter(
            MarketBreadth.market == snapshot.market,
            MarketBreadth.date == snapshot.date,
            MarketBreadth.calculation_revision == CURRENT_BREADTH_CALCULATION_REVISION,
        )
        .one_or_none()
    )
    if aggregate is None:
        raise BreadthContributorSnapshotInconsistent(
            "Matching current aggregate breadth row is unavailable"
        )

    try:
        contributors = parse_contributor_rows(
            {
                "symbol": contributor.symbol,
                "company_name": contributor.company_name,
                "ibd_industry_group": contributor.ibd_industry_group,
                "daily_change_pct": contributor.daily_change_pct,
                "signals": contributor.signals_json,
            }
            for contributor in snapshot.contributors
        )
        reconcile_contributor_aggregate(
            contributors,
            {
                definition.aggregate_field: getattr(
                    aggregate,
                    definition.aggregate_field,
                )
                for definition in BREADTH_CONTRIBUTOR_SIGNALS.values()
            },
        )
    except (BreadthContributorContractError, TypeError, ValueError) as exc:
        raise BreadthContributorSnapshotInconsistent(str(exc)) from exc

    items = tuple(
        BreadthContributorItemPayload(
            symbol=contributor.symbol,
            company_name=contributor.company_name,
            ibd_industry_group=contributor.ibd_industry_group,
            daily_change_pct=contributor.daily_change_pct,
            signals=contributor.signals,
        )
        for contributor in contributors
    )
    return BreadthContributorDocumentPayload(
        schema=CONTRIBUTOR_SCHEMA_ID,
        market=snapshot.market,
        date=snapshot.date,
        calculation_revision=CURRENT_BREADTH_CALCULATION_REVISION,
        contributors=items,
    )


def get_contributor_document(
    db: Session,
    market: str,
    calculation_date: date,
) -> BreadthContributorDocumentPayload:
    return _document_from_snapshot(
        db,
        _load_snapshot(db, market.upper(), calculation_date),
    )


def list_contributor_dates(
    db: Session,
    market: str,
    *,
    limit: int = 20,
) -> BreadthContributorIndexPayload:
    if limit < 1:
        raise ValueError("Contributor index limit must be positive")
    normalized_market = market.upper()
    snapshots = (
        db.query(MarketBreadthContributorSnapshot)
        .options(joinedload(MarketBreadthContributorSnapshot.contributors))
        .filter(MarketBreadthContributorSnapshot.market == normalized_market)
        .order_by(MarketBreadthContributorSnapshot.date.desc())
        .all()
    )
    dates: list[date] = []
    for snapshot in snapshots:
        try:
            _document_from_snapshot(db, snapshot)
        except BreadthContributorSnapshotInconsistent as exc:
            logger.warning(
                "Omitting inconsistent breadth contributor snapshot %s/%s: %s",
                normalized_market,
                snapshot.date,
                exc,
            )
            continue
        dates.append(snapshot.date)
        if len(dates) == limit:
            break
    return BreadthContributorIndexPayload(
        schema=CONTRIBUTOR_SCHEMA_ID,
        market=normalized_market,
        calculation_revision=CURRENT_BREADTH_CALCULATION_REVISION,
        dates=tuple(dates),
    )
