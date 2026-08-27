"""Point-in-time universe adapters for breadth calculations."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Iterable, Mapping
from datetime import date

import pandas as pd

from app.models.stock_universe import StockUniverse
from app.services.point_in_time_universe_service import PointInTimeUniverseService

from .formulas import signal_flags_at
from .types import (
    BreadthFormulaPolicy,
    BreadthMarketPolicy,
    BreadthUniverseMember,
    BreadthUniverseSnapshot,
    SymbolMetricEligibility,
)

BREADTH_ELIGIBILITY_SIGNATURE_VERSION = "point-in-time-common-stock-v2"


def breadth_eligibility_signature(symbols: Iterable[str]) -> str:
    """Hash canonical broad-universe membership under the current policy."""
    canonical_symbols = tuple(sorted(set(symbols)))
    payload = "".join(
        (
            f"{BREADTH_ELIGIBILITY_SIGNATURE_VERSION}\n",
            *(f"{symbol}\n" for symbol in canonical_symbols),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _snapshot_members(db, point_in_time) -> tuple[BreadthUniverseMember, ...]:
    source_members = point_in_time.members
    if not source_members and point_in_time.symbols:
        rows = (
            db.query(StockUniverse)
            .filter(StockUniverse.symbol.in_(point_in_time.symbols))
            .order_by(StockUniverse.symbol.asc())
            .all()
        )
        source_members = tuple(
            BreadthUniverseMember(
                symbol=row.symbol,
                currency=row.currency,
                is_common_stock=row.is_common_stock,
            )
            for row in rows
        )

    return tuple(
        BreadthUniverseMember(
            symbol=member.symbol,
            currency=member.currency,
            is_common_stock=member.is_common_stock,
        )
        for member in source_members
        if member.is_common_stock
    )


def build_breadth_universe_snapshots(
    db,
    market: str,
    dates: Collection[date],
    *,
    universe_service: PointInTimeUniverseService | None = None,
) -> Mapping[date, BreadthUniverseSnapshot]:
    from app.services.point_in_time_universe_service import (
        hash_point_in_time_universe_symbols,
    )

    resolver = universe_service or PointInTimeUniverseService()
    snapshots: dict[date, BreadthUniverseSnapshot] = {}
    for calculation_date in dates:
        point_in_time = resolver.resolve(
            db,
            market=market,
            as_of_date=calculation_date,
        )
        members = tuple(
            sorted(
                _snapshot_members(db, point_in_time),
                key=lambda item: item.symbol,
            )
        )
        symbols = tuple(member.symbol for member in members)
        snapshots[calculation_date] = BreadthUniverseSnapshot(
            calculation_date=calculation_date,
            members=members,
            broad_signature=hash_point_in_time_universe_symbols(symbols),
        )
    return snapshots


def classify_metric_eligibility(
    member: BreadthUniverseMember,
    features: pd.DataFrame,
    policy: BreadthFormulaPolicy,
    market_policy: BreadthMarketPolicy,
    *,
    calculation_date: date | None = None,
) -> SymbolMetricEligibility:
    if not member.is_common_stock or features.empty:
        return SymbolMetricEligibility()
    target_date = calculation_date or pd.Timestamp(features.index[-1]).date()
    return signal_flags_at(
        features,
        target_date,
        policy,
        market_policy,
        stockbee_currency_matches=(
            member.currency.upper() == market_policy.currency
        ),
    ).eligibility


def stockbee_eligible_symbols(
    snapshot: BreadthUniverseSnapshot,
    features_by_symbol: Mapping[str, pd.DataFrame],
    policy: BreadthFormulaPolicy,
    market_policy: BreadthMarketPolicy,
) -> tuple[str, ...]:
    eligible: list[str] = []
    for member in snapshot.members:
        features = features_by_symbol.get(member.symbol)
        if features is None:
            continue
        metric_eligibility = classify_metric_eligibility(
            member,
            features,
            policy,
            market_policy,
            calculation_date=snapshot.calculation_date,
        )
        if metric_eligibility.stockbee_daily:
            eligible.append(member.symbol)
    return tuple(sorted(eligible))


def stockbee_eligibility_signature(
    snapshot: BreadthUniverseSnapshot,
    features_by_symbol: Mapping[str, pd.DataFrame],
    policy: BreadthFormulaPolicy,
    market_policy: BreadthMarketPolicy,
) -> str:
    from app.services.point_in_time_universe_service import (
        hash_point_in_time_universe_symbols,
    )

    return hash_point_in_time_universe_symbols(
        stockbee_eligible_symbols(
            snapshot,
            features_by_symbol,
            policy,
            market_policy,
        )
    )
