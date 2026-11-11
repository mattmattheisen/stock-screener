"""Research-only CAN SLIM threshold comparator. Never imported by production scanning.

This compares threshold eligibility only; it does not replace C/A/S/I logic,
validate an IBD proprietary rating, or constitute a portfolio backtest.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Optional


@dataclass(frozen=True)
class Observation:
    close: Optional[float]
    rolling_52w_high: Optional[float]
    rs_rating: Optional[float]
    rs_source_verified: bool
    market_state: Optional[str]
    other_gates_pass: Optional[bool]


@dataclass(frozen=True)
class Decision:
    status: str
    n_pass: Optional[bool]
    l_pass: Optional[bool]
    allocation_fraction: float
    reason: str


def evaluate(obs: Observation, variant: str = "A") -> Decision:
    """A baseline, B M-only, C N-only, D L-only, E combined.

    Missing values never pass. M states must be explicitly normalized by
    the caller: supportive, cautionary, confirmed_downtrend.
    """
    if variant not in {"A", "B", "C", "D", "E"}:
        raise ValueError("Unknown research variant")
    if obs.other_gates_pass is not True:
        return Decision("UNAVAILABLE" if obs.other_gates_pass is None else "FAIL", None, None, 0.0, "Other original gates unverified or failed")
    if obs.close is None or obs.rolling_52w_high is None or not all(
        isfinite(x) and x > 0 for x in (obs.close, obs.rolling_52w_high)
    ):
        return Decision("UNAVAILABLE", None, None, 0.0, "Valid point-in-time close and rolling high required")
    if obs.close > obs.rolling_52w_high:
        return Decision("UNAVAILABLE", None, None, 0.0, "Inconsistent close/high")
    n_limit = 0.15 if variant in {"C", "E"} else 0.10
    n_pass = (obs.rolling_52w_high - obs.close) / obs.rolling_52w_high <= n_limit + 1e-12
    if not obs.rs_source_verified or obs.rs_rating is None or not isfinite(obs.rs_rating):
        return Decision("UNAVAILABLE", n_pass, None, 0.0, "Verified proprietary RS required")
    l_limit = 75 if variant in {"D", "E"} else 80
    l_pass = obs.rs_rating >= l_limit
    if not n_pass or not l_pass:
        return Decision("FAIL", n_pass, l_pass, 0.0, "N or L threshold failed")
    if obs.market_state == "supportive":
        return Decision("PASS", True, True, 1.0, "All supplied gates passed")
    if obs.market_state == "cautionary":
        if variant in {"B", "E"}:
            return Decision("CONDITIONAL", True, True, 0.25, "Research-only cautionary M starter; separate strength confirmation required")
        return Decision("FAIL", True, True, 0.0, "Original market restriction")
    if obs.market_state == "confirmed_downtrend":
        return Decision("FAIL", True, True, 0.0, "Confirmed downtrend")
    return Decision("UNAVAILABLE", True, True, 0.0, "Unverified market state")
