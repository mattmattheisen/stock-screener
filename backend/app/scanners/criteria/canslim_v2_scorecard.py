"""CAN SLIM V2 score aggregation and market-gating policy.

This module keeps stock quality (0-100) separate from market eligibility.
M can block a new-buy decision but can never add to or subtract from the
stock's CAN SLIM score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canslim_v2 import (
    CANSLIMLetter,
    CriterionResult,
    METHODOLOGY_VERSION,
)


REQUIRED_STOCK_PASS_LETTERS: frozenset[CANSLIMLetter] = frozenset(
    {
        CANSLIMLetter.CURRENT_EARNINGS,
        CANSLIMLetter.ANNUAL_EARNINGS,
        CANSLIMLetter.LEADER,
    }
)


@dataclass(frozen=True)
class CANSLIMV2Scorecard:
    """Aggregate stock score plus the separate market eligibility decision."""

    criteria: dict[CANSLIMLetter, CriterionResult]
    stock_score: float
    stock_passes: bool
    market_passes: bool
    actionable: bool
    status: str
    failed_required_letters: tuple[str, ...] = ()
    unavailable_required_letters: tuple[str, ...] = ()
    methodology_version: str = METHODOLOGY_VERSION

    def as_dict(self) -> dict[str, Any]:
        """Serialize the scorecard for scanner/API use."""

        return {
            "methodology_version": self.methodology_version,
            "stock_score": self.stock_score,
            "stock_passes": self.stock_passes,
            "market_passes": self.market_passes,
            "actionable": self.actionable,
            "status": self.status,
            "failed_required_letters": list(self.failed_required_letters),
            "unavailable_required_letters": list(self.unavailable_required_letters),
            "criteria": {
                letter.value: result.as_dict()
                for letter, result in sorted(
                    self.criteria.items(), key=lambda item: item[0].value
                )
            },
        }


def build_scorecard(
    results: list[CriterionResult] | tuple[CriterionResult, ...],
) -> CANSLIMV2Scorecard:
    """Combine exactly one result per CAN SLIM letter into a V2 scorecard.

    Stock qualification is deliberately distinct from market eligibility:
    M never changes the 0-100 stock score. The first V2 policy requires C, A
    and L to pass in addition to a stock score >= 70. N/S/I remain score
    contributors rather than hard gates until validation demonstrates that
    stricter gating improves out-of-sample outcomes.
    """

    by_letter: dict[CANSLIMLetter, CriterionResult] = {}
    for result in results:
        if result.letter in by_letter:
            raise ValueError(f"Duplicate CAN SLIM result for {result.letter.value}")
        by_letter[result.letter] = result

    missing = [letter.value for letter in CANSLIMLetter if letter not in by_letter]
    if missing:
        raise ValueError(f"Missing CAN SLIM results: {', '.join(missing)}")

    stock_score = round(
        sum(
            result.points
            for letter, result in by_letter.items()
            if letter is not CANSLIMLetter.MARKET
        ),
        2,
    )

    unavailable_required = tuple(
        sorted(
            letter.value
            for letter in REQUIRED_STOCK_PASS_LETTERS
            if not by_letter[letter].available
        )
    )
    failed_required = tuple(
        sorted(
            letter.value
            for letter in REQUIRED_STOCK_PASS_LETTERS
            if by_letter[letter].available and not by_letter[letter].passes
        )
    )

    stock_passes = (
        stock_score >= 70.0
        and not unavailable_required
        and not failed_required
    )
    market = by_letter[CANSLIMLetter.MARKET]
    market_passes = market.available and market.passes
    actionable = stock_passes and market_passes

    if unavailable_required:
        status = "insufficient_data"
    elif stock_passes and not market.available:
        status = "market_unknown"
    elif stock_passes and not market.passes:
        status = "market_blocked"
    elif actionable:
        status = "qualified"
    elif stock_score >= 60.0:
        status = "watchlist"
    else:
        status = "not_qualified"

    return CANSLIMV2Scorecard(
        criteria=by_letter,
        stock_score=stock_score,
        stock_passes=stock_passes,
        market_passes=market_passes,
        actionable=actionable,
        status=status,
        failed_required_letters=failed_required,
        unavailable_required_letters=unavailable_required,
    )
