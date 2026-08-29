"""Shared contract for breadth indicators that support stock drilldown."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Literal, Mapping

from .types import BreadthContributorSnapshotResult, BreadthDailyResult


CONTRIBUTOR_SCHEMA_ID = "breadth-contributors-v1"
CONTRIBUTOR_RETENTION_SESSIONS = 20
NO_GROUP_LABEL = "No Group"


@dataclass(frozen=True, slots=True)
class BreadthContributorSignalDefinition:
    signal_key: str
    aggregate_field: str
    direction: Literal["up", "down", "extension"]
    value_kind: Literal["percent", "multiple"]


_SIGNALS = (
    BreadthContributorSignalDefinition("up_4pct", "stocks_up_4pct", "up", "percent"),
    BreadthContributorSignalDefinition("down_4pct", "stocks_down_4pct", "down", "percent"),
    BreadthContributorSignalDefinition("up_25pct_quarter", "stocks_up_25pct_quarter", "up", "percent"),
    BreadthContributorSignalDefinition("down_25pct_quarter", "stocks_down_25pct_quarter", "down", "percent"),
    BreadthContributorSignalDefinition("up_25pct_month", "stocks_up_25pct_month", "up", "percent"),
    BreadthContributorSignalDefinition("down_25pct_month", "stocks_down_25pct_month", "down", "percent"),
    BreadthContributorSignalDefinition("up_50pct_month", "stocks_up_50pct_month", "up", "percent"),
    BreadthContributorSignalDefinition("down_50pct_month", "stocks_down_50pct_month", "down", "percent"),
    BreadthContributorSignalDefinition("up_13pct_34days", "stocks_up_13pct_34days", "up", "percent"),
    BreadthContributorSignalDefinition("down_13pct_34days", "stocks_down_13pct_34days", "down", "percent"),
    BreadthContributorSignalDefinition("atr_10x_extension", "atr_10x_extension_count", "extension", "multiple"),
)

BREADTH_CONTRIBUTOR_SIGNALS: Mapping[str, BreadthContributorSignalDefinition] = (
    MappingProxyType({definition.signal_key: definition for definition in _SIGNALS})
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

    counts = {signal_key: 0 for signal_key in BREADTH_CONTRIBUTOR_SIGNALS}
    symbols: set[str] = set()
    for contributor in snapshot.contributors:
        if contributor.symbol in symbols:
            raise ValueError(
                f"Duplicate breadth contributor symbol {contributor.symbol}"
            )
        symbols.add(contributor.symbol)
        if contributor.daily_change_pct is not None and not math.isfinite(
            contributor.daily_change_pct
        ):
            raise ValueError(
                f"Nonfinite daily change for breadth contributor {contributor.symbol}"
            )
        if not contributor.signals:
            raise ValueError(
                f"Breadth contributor {contributor.symbol} has no qualifying signals"
            )
        for signal_key, value in contributor.signals.items():
            if signal_key not in counts:
                raise ValueError(f"Unknown breadth contributor signal {signal_key}")
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(
                    f"Invalid breadth contributor value for {signal_key}"
                )
            counts[signal_key] += 1

    for signal_key, definition in BREADTH_CONTRIBUTOR_SIGNALS.items():
        aggregate_count = int(getattr(aggregate.values, definition.aggregate_field))
        if counts[signal_key] != aggregate_count:
            raise ValueError(
                f"Contributor count mismatch for {definition.aggregate_field}: "
                f"contributors={counts[signal_key]}, aggregate={aggregate_count}"
            )
