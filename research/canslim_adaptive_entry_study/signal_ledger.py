"""Deterministic, read-only CAN SLIM signal ledger.

Each record is a decision-time evidence snapshot. No orders, backtest returns,
future-data filling, or portfolio claims are made.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .evidence import ResearchSnapshot, assess

VARIANTS = ("A", "B", "C", "D", "E")


@dataclass(frozen=True)
class SignalRow:
    symbol: str
    as_of: datetime
    variant: str
    status: str
    allocation_fraction: float
    n_pass: bool | None
    l_pass: bool | None
    reason: str


def build_ledger(records: Iterable[tuple[str, ResearchSnapshot]]) -> list[SignalRow]:
    """Sort and evaluate snapshots; reject duplicate symbol/decision timestamps."""
    indexed = list(records)
    seen: set[tuple[str, datetime]] = set()
    for symbol, snapshot in indexed:
        if not symbol or symbol != symbol.strip().upper():
            raise ValueError("Symbol must be a nonempty uppercase ticker")
        key = (symbol, snapshot.as_of)
        if key in seen:
            raise ValueError("Duplicate symbol/as_of snapshot")
        seen.add(key)
    rows = []
    for symbol, snapshot in sorted(indexed, key=lambda r: (r[1].as_of, r[0])):
        for variant in VARIANTS:
            d = assess(snapshot, variant)
            rows.append(SignalRow(symbol, snapshot.as_of, variant, d.status, d.allocation_fraction, d.n_pass, d.l_pass, d.reason))
    return rows


def incremental_eligibility(rows: Iterable[SignalRow]) -> dict[str, int]:
    """Count additional eligible symbol/dates vs A; conditional is separate.

    These are *signal counts*, not trade counts or returns.
    """
    by_key: dict[tuple[str, datetime], dict[str, SignalRow]] = {}
    for row in rows:
        key = (row.symbol, row.as_of)
        if row.variant in by_key.setdefault(key, {}):
            raise ValueError("Duplicate signal row")
        by_key[key][row.variant] = row
    counts = {f"{v}_extra_pass": 0 for v in VARIANTS[1:]}
    counts.update({f"{v}_extra_conditional": 0 for v in VARIANTS[1:]})
    for group in by_key.values():
        if set(group) != set(VARIANTS):
            raise ValueError("Incomplete variant group")
        if group["A"].status in ("PASS", "CONDITIONAL"):
            continue
        for v in VARIANTS[1:]:
            if group[v].status == "PASS":
                counts[f"{v}_extra_pass"] += 1
            elif group[v].status == "CONDITIONAL":
                counts[f"{v}_extra_conditional"] += 1
    return counts
