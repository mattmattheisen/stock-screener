"""Shared contract for breadth indicators that support stock drilldown."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from .types import (
    BreadthContributor,
    BreadthContributorSnapshotResult,
    BreadthDailyResult,
)

CONTRIBUTOR_SCHEMA_ID = "breadth-contributors-v1"
CONTRIBUTOR_RETENTION_SESSIONS = 20
NO_GROUP_LABEL = "No Group"


@dataclass(frozen=True, slots=True)
class BreadthContributorSignalDefinition:
    signal_key: str
    signal_attribute: str
    aggregate_field: str
    direction: Literal["up", "down", "extension"]
    value_kind: Literal["percent", "multiple"]


_SIGNALS = (
    BreadthContributorSignalDefinition(
        "up_4pct", "up_4pct", "stocks_up_4pct", "up", "percent"
    ),
    BreadthContributorSignalDefinition(
        "down_4pct", "down_4pct", "stocks_down_4pct", "down", "percent"
    ),
    BreadthContributorSignalDefinition(
        "up_25pct_quarter",
        "up_25pct_quarter",
        "stocks_up_25pct_quarter",
        "up",
        "percent",
    ),
    BreadthContributorSignalDefinition(
        "down_25pct_quarter",
        "down_25pct_quarter",
        "stocks_down_25pct_quarter",
        "down",
        "percent",
    ),
    BreadthContributorSignalDefinition(
        "up_25pct_month", "up_25pct_month", "stocks_up_25pct_month", "up", "percent"
    ),
    BreadthContributorSignalDefinition(
        "down_25pct_month",
        "down_25pct_month",
        "stocks_down_25pct_month",
        "down",
        "percent",
    ),
    BreadthContributorSignalDefinition(
        "up_50pct_month", "up_50pct_month", "stocks_up_50pct_month", "up", "percent"
    ),
    BreadthContributorSignalDefinition(
        "down_50pct_month",
        "down_50pct_month",
        "stocks_down_50pct_month",
        "down",
        "percent",
    ),
    BreadthContributorSignalDefinition(
        "up_13pct_34days", "up_13pct_34days", "stocks_up_13pct_34days", "up", "percent"
    ),
    BreadthContributorSignalDefinition(
        "down_13pct_34days",
        "down_13pct_34days",
        "stocks_down_13pct_34days",
        "down",
        "percent",
    ),
    BreadthContributorSignalDefinition(
        "atr_10x_extension",
        "atr_10x_extension",
        "atr_10x_extension_count",
        "extension",
        "multiple",
    ),
)

BREADTH_CONTRIBUTOR_SIGNALS: Mapping[str, BreadthContributorSignalDefinition] = (
    MappingProxyType({definition.signal_key: definition for definition in _SIGNALS})
)


class BreadthContributorContractError(ValueError):
    """Contributor rows or counts violate the shared transport contract."""


def parse_contributor_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[BreadthContributor, ...]:
    contributors: list[BreadthContributor] = []
    symbols: set[str] = set()
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol or symbol in symbols:
            raise BreadthContributorContractError(
                f"Duplicate or blank contributor symbol {symbol!r}"
            )
        symbols.add(symbol)
        company_name = row.get("company_name")
        if company_name is not None and not isinstance(company_name, str):
            raise BreadthContributorContractError(
                f"Invalid company name for contributor {symbol}"
            )
        normalized_company_name = (
            company_name.strip() if company_name is not None else None
        ) or None
        daily_change = row.get("daily_change_pct")
        if isinstance(daily_change, bool):
            raise BreadthContributorContractError(
                f"Invalid daily change for contributor {symbol}"
            )
        try:
            normalized_daily_change = (
                float(daily_change) if daily_change is not None else None
            )
        except (TypeError, ValueError) as exc:
            raise BreadthContributorContractError(
                f"Invalid daily change for contributor {symbol}"
            ) from exc
        if normalized_daily_change is not None and not math.isfinite(
            normalized_daily_change
        ):
            raise BreadthContributorContractError(
                f"Invalid daily change for contributor {symbol}"
            )
        raw_signals = row.get("signals")
        if not isinstance(raw_signals, Mapping) or not raw_signals:
            raise BreadthContributorContractError(
                f"Contributor {symbol} has no valid signals"
            )
        signals: dict[str, float] = {}
        for signal_key, raw_value in raw_signals.items():
            if signal_key not in BREADTH_CONTRIBUTOR_SIGNALS:
                raise BreadthContributorContractError(
                    f"Unknown breadth contributor signal {signal_key}"
                )
            if isinstance(raw_value, bool):
                raise BreadthContributorContractError(
                    f"Invalid breadth contributor value for {signal_key}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise BreadthContributorContractError(
                    f"Invalid breadth contributor value for {signal_key}"
                ) from exc
            if not math.isfinite(value):
                raise BreadthContributorContractError(
                    f"Invalid breadth contributor value for {signal_key}"
                )
            signals[signal_key] = value
        group = str(row.get("ibd_industry_group") or "").strip() or NO_GROUP_LABEL
        contributors.append(
            BreadthContributor(
                symbol=symbol,
                company_name=normalized_company_name,
                ibd_industry_group=group,
                daily_change_pct=normalized_daily_change,
                signals=MappingProxyType(signals),
            )
        )
    return tuple(sorted(contributors, key=lambda item: item.symbol))


def contributor_signal_counts(
    contributors: Iterable[BreadthContributor],
) -> Mapping[str, int]:
    counts = {signal_key: 0 for signal_key in BREADTH_CONTRIBUTOR_SIGNALS}
    for contributor in contributors:
        for signal_key in contributor.signals:
            counts[signal_key] += 1
    return MappingProxyType(counts)


def reconcile_contributor_aggregate(
    contributors: Iterable[BreadthContributor],
    aggregate: Mapping[str, Any],
) -> None:
    counts = contributor_signal_counts(contributors)
    for signal_key, definition in BREADTH_CONTRIBUTOR_SIGNALS.items():
        aggregate_count = int(aggregate[definition.aggregate_field])
        if counts[signal_key] != aggregate_count:
            raise BreadthContributorContractError(
                f"Contributor count mismatch for {definition.aggregate_field}: "
                f"contributors={counts[signal_key]}, aggregate={aggregate_count}"
            )


def reconcile_contributor_counts(
    snapshot: BreadthContributorSnapshotResult,
    aggregate: BreadthDailyResult,
) -> None:
    """Fail when a snapshot cannot be the source of its aggregate counts."""
    if (
        snapshot.market != aggregate.market
        or snapshot.calculation_date != aggregate.calculation_date
        or snapshot.calculation_revision != aggregate.calculation_revision
    ):
        raise ValueError("Contributor snapshot identity does not match aggregate")
    if snapshot.schema_id != CONTRIBUTOR_SCHEMA_ID:
        raise ValueError(f"Unsupported contributor schema {snapshot.schema_id!r}")

    contributors = parse_contributor_rows(
        {
            "symbol": contributor.symbol,
            "company_name": contributor.company_name,
            "ibd_industry_group": contributor.ibd_industry_group,
            "daily_change_pct": contributor.daily_change_pct,
            "signals": contributor.signals,
        }
        for contributor in snapshot.contributors
    )
    reconcile_contributor_aggregate(
        contributors,
        {
            definition.aggregate_field: getattr(
                aggregate.values,
                definition.aggregate_field,
            )
            for definition in BREADTH_CONTRIBUTOR_SIGNALS.values()
        },
    )
