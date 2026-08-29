"""Validated read model for persisted breadth contributor snapshots."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from sqlalchemy.orm import Session, joinedload

from app.models.breadth_contributor import (
    MarketBreadthContributorSnapshot,
)
from app.models.market_breadth import MarketBreadth

from .contributors import BREADTH_CONTRIBUTOR_SIGNALS, CONTRIBUTOR_SCHEMA_ID
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
            MarketBreadth.calculation_revision
            == CURRENT_BREADTH_CALCULATION_REVISION,
        )
        .one_or_none()
    )
    if aggregate is None:
        raise BreadthContributorSnapshotInconsistent(
            "Matching current aggregate breadth row is unavailable"
        )

    counts = {key: 0 for key in BREADTH_CONTRIBUTOR_SIGNALS}
    symbols: set[str] = set()
    items: list[BreadthContributorItemPayload] = []
    for contributor in snapshot.contributors:
        symbol = str(contributor.symbol or "").strip()
        if not symbol or symbol in symbols:
            raise BreadthContributorSnapshotInconsistent(
                f"Duplicate or blank contributor symbol {symbol!r}"
            )
        symbols.add(symbol)
        daily_change = contributor.daily_change_pct
        if daily_change is not None and not math.isfinite(float(daily_change)):
            raise BreadthContributorSnapshotInconsistent(
                f"Nonfinite daily change for {symbol}"
            )
        raw_signals = contributor.signals_json
        if not isinstance(raw_signals, dict) or not raw_signals:
            raise BreadthContributorSnapshotInconsistent(
                f"Contributor {symbol} has no valid signals"
            )
        signals: dict[str, float] = {}
        for signal_key, raw_value in raw_signals.items():
            if signal_key not in counts:
                raise BreadthContributorSnapshotInconsistent(
                    f"Unknown breadth contributor signal {signal_key}"
                )
            if isinstance(raw_value, bool):
                raise BreadthContributorSnapshotInconsistent(
                    f"Invalid breadth contributor value for {signal_key}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise BreadthContributorSnapshotInconsistent(
                    f"Invalid breadth contributor value for {signal_key}"
                ) from exc
            if not math.isfinite(value):
                raise BreadthContributorSnapshotInconsistent(
                    f"Invalid breadth contributor value for {signal_key}"
                )
            signals[signal_key] = value
            counts[signal_key] += 1
        items.append(
            BreadthContributorItemPayload(
                symbol=symbol,
                company_name=contributor.company_name,
                ibd_industry_group=contributor.ibd_industry_group,
                daily_change_pct=(
                    float(daily_change) if daily_change is not None else None
                ),
                signals=MappingProxyType(signals),
            )
        )

    for signal_key, definition in BREADTH_CONTRIBUTOR_SIGNALS.items():
        aggregate_count = getattr(aggregate, definition.aggregate_field)
        if counts[signal_key] != aggregate_count:
            raise BreadthContributorSnapshotInconsistent(
                f"Contributor count mismatch for {definition.aggregate_field}: "
                f"contributors={counts[signal_key]}, aggregate={aggregate_count}"
            )
    return BreadthContributorDocumentPayload(
        schema=CONTRIBUTOR_SCHEMA_ID,
        market=snapshot.market,
        date=snapshot.date,
        calculation_revision=CURRENT_BREADTH_CALCULATION_REVISION,
        contributors=tuple(sorted(items, key=lambda item: item.symbol)),
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
