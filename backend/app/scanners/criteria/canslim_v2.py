"""Pure, deterministic CAN SLIM V2 criterion scoring primitives.

This module is intentionally not registered as a scanner yet. It creates a
stable, testable contract for evolving the methodology letter-by-letter without
changing the legacy CANSLIM scanner's production behaviour.

Methodology notes
-----------------
C (Current quarterly earnings) is anchored to the most recent quarter's EPS
change versus the comparable quarter one year earlier. Prior-quarter EPS YoY
and current-quarter sales YoY are confirmations, not substitutes.

A (Annual earnings) is anchored to multi-year EPS CAGR and requires enough
annual observations to evaluate a genuine multi-year trend. EPS Rating and ROE
are optional confirmations.

N/S/L/I are represented in the contract but will be implemented in subsequent
slices. M is deliberately a scan-level market gate, not part of the 100-point
stock score.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


METHODOLOGY_VERSION = "canslim_v2"


class CANSLIMLetter(str, Enum):
    """Canonical CAN SLIM criterion identifiers."""

    CURRENT_EARNINGS = "C"
    ANNUAL_EARNINGS = "A"
    NEW = "N"
    SUPPLY_DEMAND = "S"
    LEADER = "L"
    INSTITUTIONAL = "I"
    MARKET = "M"


STOCK_SCORE_MAX_POINTS: dict[CANSLIMLetter, float] = {
    CANSLIMLetter.CURRENT_EARNINGS: 20.0,
    CANSLIMLetter.ANNUAL_EARNINGS: 15.0,
    CANSLIMLetter.NEW: 15.0,
    CANSLIMLetter.SUPPLY_DEMAND: 15.0,
    CANSLIMLetter.LEADER: 20.0,
    CANSLIMLetter.INSTITUTIONAL: 15.0,
    CANSLIMLetter.MARKET: 0.0,
}


@dataclass(frozen=True)
class CriterionResult:
    """Normalized output contract for one CAN SLIM criterion.

    ``available`` means the minimum data needed to evaluate the criterion is
    present. Optional confirmation metrics may still be missing.
    """

    letter: CANSLIMLetter
    points: float
    max_points: float
    passes: bool
    available: bool
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    methodology_version: str = METHODOLOGY_VERSION

    def __post_init__(self) -> None:
        if self.max_points < 0:
            raise ValueError("max_points must be non-negative")
        if self.points < 0 or self.points > self.max_points:
            raise ValueError("points must be between 0 and max_points")
        expected_max = STOCK_SCORE_MAX_POINTS[self.letter]
        if self.max_points != expected_max:
            raise ValueError(
                f"{self.letter.value} max_points must be {expected_max}, "
                f"got {self.max_points}"
            )

    def as_dict(self) -> dict[str, Any]:
        """Serialize the contract using the letter value rather than Enum repr."""

        payload = asdict(self)
        payload["letter"] = self.letter.value
        return payload


def unavailable(letter: CANSLIMLetter, reason: str, **metrics: Any) -> CriterionResult:
    """Return a deterministic unavailable result for a criterion."""

    return CriterionResult(
        letter=letter,
        points=0.0,
        max_points=STOCK_SCORE_MAX_POINTS[letter],
        passes=False,
        available=False,
        reason=reason,
        metrics=metrics,
    )


def score_current_earnings(
    *,
    eps_yoy: float | None,
    prior_eps_yoy: float | None = None,
    sales_yoy: float | None = None,
) -> CriterionResult:
    """Score C: current quarterly earnings, maximum 20 points.

    The pass gate is EPS growth of at least 25% versus the same quarter one
    year earlier. Acceleration and strong sales growth can add confirmation
    points, but cannot turn a sub-25% EPS quarter into a pass.
    """

    letter = CANSLIMLetter.CURRENT_EARNINGS
    max_points = STOCK_SCORE_MAX_POINTS[letter]
    if eps_yoy is None:
        return unavailable(
            letter,
            "Most recent quarter EPS YoY growth is unavailable",
            eps_yoy=None,
            prior_eps_yoy=prior_eps_yoy,
            sales_yoy=sales_yoy,
        )

    if eps_yoy >= 50:
        points = 18.0
    elif eps_yoy >= 40:
        points = 17.0
    elif eps_yoy >= 25:
        points = 15.0
    elif eps_yoy >= 15:
        points = 10.0
    elif eps_yoy > 0:
        points = 5.0
    else:
        points = 0.0

    accelerating = prior_eps_yoy is not None and eps_yoy > prior_eps_yoy
    sales_confirmation = sales_yoy is not None and sales_yoy >= 25
    if accelerating:
        points += 1.0
    if sales_confirmation:
        points += 1.0
    points = min(points, max_points)

    return CriterionResult(
        letter=letter,
        points=points,
        max_points=max_points,
        passes=eps_yoy >= 25,
        available=True,
        reason=(
            f"Current-quarter EPS YoY growth {eps_yoy:.1f}%"
            + ("; accelerating" if accelerating else "")
            + ("; sales confirmation" if sales_confirmation else "")
        ),
        metrics={
            "eps_yoy": eps_yoy,
            "prior_eps_yoy": prior_eps_yoy,
            "sales_yoy": sales_yoy,
            "eps_accelerating": accelerating,
            "sales_confirmation": sales_confirmation,
        },
    )


def score_annual_earnings(
    *,
    eps_cagr: float | None,
    years_available: int,
    eps_rating: float | None = None,
    roe: float | None = None,
) -> CriterionResult:
    """Score A: annual earnings growth, maximum 15 points.

    A faithful multi-year annual-growth evaluation needs at least four annual
    EPS observations (three growth intervals). With less history the criterion
    is marked unavailable rather than silently substituting a quarterly proxy.

    The pass gate is EPS CAGR >= 25%. Strong EPS Rating and ROE are optional
    confirmations worth one point each.
    """

    letter = CANSLIMLetter.ANNUAL_EARNINGS
    max_points = STOCK_SCORE_MAX_POINTS[letter]
    if eps_cagr is None:
        return unavailable(
            letter,
            "Multi-year EPS CAGR is unavailable",
            eps_cagr=None,
            years_available=years_available,
            eps_rating=eps_rating,
            roe=roe,
        )
    if years_available < 4:
        return unavailable(
            letter,
            "At least four annual EPS observations are required",
            eps_cagr=eps_cagr,
            years_available=years_available,
            eps_rating=eps_rating,
            roe=roe,
        )

    if eps_cagr >= 30:
        points = 13.0
    elif eps_cagr >= 25:
        points = 12.0
    elif eps_cagr >= 15:
        points = 9.0
    elif eps_cagr >= 10:
        points = 6.0
    elif eps_cagr > 0:
        points = 3.0
    else:
        points = 0.0

    eps_rating_confirmation = eps_rating is not None and eps_rating >= 80
    roe_confirmation = roe is not None and roe >= 17
    if eps_rating_confirmation:
        points += 1.0
    if roe_confirmation:
        points += 1.0
    points = min(points, max_points)

    return CriterionResult(
        letter=letter,
        points=points,
        max_points=max_points,
        passes=eps_cagr >= 25,
        available=True,
        reason=f"Multi-year EPS CAGR {eps_cagr:.1f}% across {years_available} observations",
        metrics={
            "eps_cagr": eps_cagr,
            "years_available": years_available,
            "eps_rating": eps_rating,
            "roe": roe,
            "eps_rating_confirmation": eps_rating_confirmation,
            "roe_confirmation": roe_confirmation,
        },
    )
