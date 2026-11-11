"""Fail-closed point-in-time evidence adapter for adaptive CAN SLIM research.

This module intentionally does not fetch data or invent missing historical
fundamentals/ratings. Each input must carry an availability timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Generic, TypeVar

from .comparator import Observation, Decision, evaluate

T = TypeVar("T")


@dataclass(frozen=True)
class Evidence(Generic[T]):
    value: T | None
    available_at: datetime | None
    source: str


@dataclass(frozen=True)
class ResearchSnapshot:
    as_of: datetime
    close: Evidence[float]
    rolling_52w_high: Evidence[float]
    proprietary_rs: Evidence[float]
    market_state: Evidence[str]
    c_pass: Evidence[bool]
    a_pass: Evidence[bool]
    s_pass: Evidence[bool]
    i_pass: Evidence[bool]
    stock_strength_confirmed: Evidence[bool]


def _available(item: Evidence, as_of: datetime) -> bool:
    if item.available_at is None or item.value is None or not item.source.strip():
        return False
    if item.available_at.tzinfo is None or as_of.tzinfo is None:
        return False
    return item.available_at <= as_of


def _pass(item: Evidence[bool], as_of: datetime) -> bool | None:
    if not _available(item, as_of) or type(item.value) is not bool:
        return None
    return item.value


def assess(snapshot: ResearchSnapshot, variant: str = "A") -> Decision:
    """Only known-as-of evidence can qualify; later reports cannot leak backward."""
    at = snapshot.as_of
    if at.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    gates = [_pass(x, at) for x in (snapshot.c_pass, snapshot.a_pass, snapshot.s_pass, snapshot.i_pass)]
    other = False if False in gates else (None if None in gates else True)

    def numeric(item: Evidence[float]) -> float | None:
        if not _available(item, at) or type(item.value) not in (float, int):
            return None
        return float(item.value) if isfinite(float(item.value)) else None

    market = snapshot.market_state.value if _available(snapshot.market_state, at) else None
    if market not in ("supportive", "cautionary", "confirmed_downtrend"):
        market = None
    rs_source_verified = (
        _available(snapshot.proprietary_rs, at)
        and snapshot.proprietary_rs.source == "licensed_ibd_rs"
    )
    decision = evaluate(
        Observation(
            close=numeric(snapshot.close),
            rolling_52w_high=numeric(snapshot.rolling_52w_high),
            rs_rating=numeric(snapshot.proprietary_rs),
            rs_source_verified=rs_source_verified,
            market_state=market,
            other_gates_pass=other,
        ),
        variant,
    )
    if decision.status == "CONDITIONAL":
        strength = _pass(snapshot.stock_strength_confirmed, at)
        if strength is not True:
            return Decision(
                "UNAVAILABLE" if strength is None else "FAIL",
                decision.n_pass,
                decision.l_pass,
                0.0,
                "Cautionary M starter requires verified stock-strength confirmation",
            )
    return decision
