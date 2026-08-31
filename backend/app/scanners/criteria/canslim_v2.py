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

N (New) uses proximity to a 52-week high as the objective, reproducible core.
Recent catalyst evidence and breakout volume are confirmations, not substitutes
for price leadership.

S (Supply and demand) requires evidence of demand from accumulation volume.
Smaller share supply is a modest confirmation and can never rescue weak demand.

L (Leader) is anchored to the repository's canonical relative-strength rating.
Industry-group leadership is a confirmation, not a substitute for stock RS.

I (Institutional sponsorship) rewards meaningful sponsorship plus evidence that
sponsorship is increasing. It deliberately avoids the legacy "50-70% sweet
spot" because CAN SLIM calls for quality/increasing sponsorship, not a narrow
static ownership band.

M (Market) is deliberately a scan-level gate, not part of the 100-point stock
score. It consumes the repository's existing 0-100 market-exposure score.
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

MARKET_STANCE_BANDS: tuple[tuple[float, str, str], ...] = (
    (85.0, "Power Trend", "aggressive"),
    (65.0, "Confirmed Uptrend", "normal"),
    (50.0, "Uptrend Under Pressure", "reduced"),
    (30.0, "Downtrend/Caution", "watchlist_only"),
    (0.0, "Correction — In Cash", "cash"),
)


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


def score_new_highs(
    *,
    distance_from_52w_high_pct: float | None,
    catalyst_recent: bool | None = None,
    breakout_volume_ratio: float | None = None,
) -> CriterionResult:
    """Score N: new highs / objective evidence of something new.

    Price proximity to the 52-week high is the reproducible core. A recent
    catalyst and breakout volume can add confirmation points. Neither can make
    a stock more than 10% below its 52-week high pass N.
    """

    letter = CANSLIMLetter.NEW
    max_points = STOCK_SCORE_MAX_POINTS[letter]
    if distance_from_52w_high_pct is None:
        return unavailable(
            letter,
            "Distance from 52-week high is unavailable",
            distance_from_52w_high_pct=None,
            catalyst_recent=catalyst_recent,
            breakout_volume_ratio=breakout_volume_ratio,
        )

    distance = max(0.0, float(distance_from_52w_high_pct))
    if distance <= 2:
        points = 13.0
    elif distance <= 5:
        points = 12.0
    elif distance <= 10:
        points = 10.0
    elif distance <= 15:
        points = 7.0
    elif distance <= 25:
        points = 3.0
    else:
        points = 0.0

    catalyst_confirmation = catalyst_recent is True
    volume_confirmation = (
        breakout_volume_ratio is not None and breakout_volume_ratio >= 1.5
    )
    if catalyst_confirmation:
        points += 1.0
    if volume_confirmation:
        points += 1.0
    points = min(points, max_points)

    return CriterionResult(
        letter=letter,
        points=points,
        max_points=max_points,
        passes=distance <= 10.0,
        available=True,
        reason=f"{distance:.1f}% below 52-week high",
        metrics={
            "distance_from_52w_high_pct": distance,
            "catalyst_recent": catalyst_recent,
            "breakout_volume_ratio": breakout_volume_ratio,
            "catalyst_confirmation": catalyst_confirmation,
            "volume_confirmation": volume_confirmation,
        },
    )


def score_supply_demand(
    *,
    up_down_volume_ratio: float | None,
    volume_surge_ratio: float | None = None,
    shares_outstanding_millions: float | None = None,
) -> CriterionResult:
    """Score S: supply and demand, maximum 15 points.

    Persistent up/down-volume evidence supplies the core score. A strong
    current volume surge can confirm demand. Smaller share supply is a limited
    confirmation (maximum two points) and can never rescue weak demand.
    """

    letter = CANSLIMLetter.SUPPLY_DEMAND
    max_points = STOCK_SCORE_MAX_POINTS[letter]
    if up_down_volume_ratio is None:
        return unavailable(
            letter,
            "Up/down volume ratio is unavailable",
            up_down_volume_ratio=None,
            volume_surge_ratio=volume_surge_ratio,
            shares_outstanding_millions=shares_outstanding_millions,
        )

    ratio = max(0.0, float(up_down_volume_ratio))
    if ratio >= 1.5:
        points = 10.0
    elif ratio >= 1.3:
        points = 8.0
    elif ratio >= 1.1:
        points = 5.0
    elif ratio > 1.0:
        points = 3.0
    else:
        points = 0.0

    if volume_surge_ratio is None:
        volume_points = 0.0
    elif volume_surge_ratio >= 2.0:
        volume_points = 3.0
    elif volume_surge_ratio >= 1.5:
        volume_points = 2.0
    elif volume_surge_ratio >= 1.2:
        volume_points = 1.0
    else:
        volume_points = 0.0

    if shares_outstanding_millions is None:
        supply_points = 0.0
    elif shares_outstanding_millions <= 25:
        supply_points = 2.0
    elif shares_outstanding_millions <= 75:
        supply_points = 1.5
    elif shares_outstanding_millions <= 150:
        supply_points = 1.0
    elif shares_outstanding_millions <= 400:
        supply_points = 0.5
    else:
        supply_points = 0.0

    points = min(points + volume_points + supply_points, max_points)
    strong_demand = ratio >= 1.3 or (
        ratio >= 1.1
        and volume_surge_ratio is not None
        and volume_surge_ratio >= 1.5
    )

    return CriterionResult(
        letter=letter,
        points=points,
        max_points=max_points,
        passes=strong_demand,
        available=True,
        reason=f"Up/down volume ratio {ratio:.2f}",
        metrics={
            "up_down_volume_ratio": ratio,
            "volume_surge_ratio": volume_surge_ratio,
            "shares_outstanding_millions": shares_outstanding_millions,
            "volume_points": volume_points,
            "supply_points": supply_points,
            "strong_demand": strong_demand,
        },
    )


def score_leader(
    *,
    rs_rating: float | None,
    group_rank: int | None = None,
) -> CriterionResult:
    """Score L: leader or laggard, maximum 20 points.

    The canonical market-universe RS rating is the primary metric. A leading
    industry group can add confirmation points but cannot rescue RS below 80.
    """

    letter = CANSLIMLetter.LEADER
    max_points = STOCK_SCORE_MAX_POINTS[letter]
    if rs_rating is None:
        return unavailable(
            letter,
            "Relative-strength rating is unavailable",
            rs_rating=None,
            group_rank=group_rank,
        )

    rs = float(rs_rating)
    if rs >= 90:
        points = 18.0
    elif rs >= 80:
        points = 15.0
    elif rs >= 70:
        points = 10.0
    elif rs >= 50:
        points = 5.0
    else:
        points = 0.0

    if group_rank is not None and group_rank <= 20:
        group_points = 2.0
    elif group_rank is not None and group_rank <= 40:
        group_points = 1.0
    else:
        group_points = 0.0
    points = min(points + group_points, max_points)

    return CriterionResult(
        letter=letter,
        points=points,
        max_points=max_points,
        passes=rs >= 80.0,
        available=True,
        reason=f"RS rating {rs:.1f}",
        metrics={
            "rs_rating": rs,
            "group_rank": group_rank,
            "group_points": group_points,
        },
    )


def score_institutional_sponsorship(
    *,
    institutional_ownership_pct: float | None,
    ownership_change_pct: float | None = None,
    institutional_transactions_pct: float | None = None,
) -> CriterionResult:
    """Score I: institutional sponsorship, maximum 15 points.

    Current sponsorship earns the base score. Increasing ownership and positive
    institutional transactions are confirmations. This intentionally does not
    penalize ownership above an arbitrary "sweet spot".

    The V2 pass gate requires at least 5% institutional ownership plus at least
    one positive trend signal. Until fund-count/quality data exists, the result
    should be treated as a transparent partial implementation of O'Neil's I.
    """

    letter = CANSLIMLetter.INSTITUTIONAL
    max_points = STOCK_SCORE_MAX_POINTS[letter]
    if institutional_ownership_pct is None:
        return unavailable(
            letter,
            "Institutional ownership is unavailable",
            institutional_ownership_pct=None,
            ownership_change_pct=ownership_change_pct,
            institutional_transactions_pct=institutional_transactions_pct,
        )

    ownership = max(0.0, float(institutional_ownership_pct))
    if ownership >= 20:
        points = 9.0
    elif ownership >= 10:
        points = 7.0
    elif ownership >= 5:
        points = 5.0
    elif ownership > 0:
        points = 3.0
    else:
        points = 0.0

    if ownership_change_pct is None:
        trend_points = 0.0
    elif ownership_change_pct >= 5:
        trend_points = 3.0
    elif ownership_change_pct > 0:
        trend_points = 2.0
    else:
        trend_points = 0.0

    if institutional_transactions_pct is None:
        transaction_points = 0.0
    elif institutional_transactions_pct >= 5:
        transaction_points = 3.0
    elif institutional_transactions_pct > 0:
        transaction_points = 2.0
    else:
        transaction_points = 0.0

    points = min(points + trend_points + transaction_points, max_points)
    increasing_sponsorship = (
        (ownership_change_pct is not None and ownership_change_pct > 0)
        or (
            institutional_transactions_pct is not None
            and institutional_transactions_pct > 0
        )
    )

    return CriterionResult(
        letter=letter,
        points=points,
        max_points=max_points,
        passes=ownership >= 5.0 and increasing_sponsorship,
        available=True,
        reason=(
            f"Institutional ownership {ownership:.1f}%"
            + ("; sponsorship increasing" if increasing_sponsorship else "")
        ),
        metrics={
            "institutional_ownership_pct": ownership,
            "ownership_change_pct": ownership_change_pct,
            "institutional_transactions_pct": institutional_transactions_pct,
            "trend_points": trend_points,
            "transaction_points": transaction_points,
            "increasing_sponsorship": increasing_sponsorship,
            "implementation_scope": "ownership_and_trend_only",
        },
    )


def score_market_gate(*, exposure_score: float | None) -> CriterionResult:
    """Score M as a zero-point market eligibility gate.

    The repository's existing market-exposure service already converts trend,
    distribution, breadth and VIX inputs into a transparent 0-100 score. V2
    reuses that score instead of inventing a second market model.

    Exposure >= 50 remains eligible for new CAN SLIM candidates, but the
    50-64.9 "Uptrend Under Pressure" band is marked reduced. Below 50, new-buy
    eligibility is blocked.
    """

    letter = CANSLIMLetter.MARKET
    max_points = STOCK_SCORE_MAX_POINTS[letter]
    if exposure_score is None:
        return unavailable(
            letter,
            "Market exposure score is unavailable",
            exposure_score=None,
        )

    score = max(0.0, min(100.0, float(exposure_score)))
    stance = MARKET_STANCE_BANDS[-1][1]
    action = MARKET_STANCE_BANDS[-1][2]
    for lower, label, mapped_action in MARKET_STANCE_BANDS:
        if score >= lower:
            stance = label
            action = mapped_action
            break

    return CriterionResult(
        letter=letter,
        points=0.0,
        max_points=max_points,
        passes=score >= 50.0,
        available=True,
        reason=f"Market exposure {score:.1f}: {stance}",
        metrics={
            "exposure_score": score,
            "stance": stance,
            "action": action,
            "new_buy_eligible": score >= 50.0,
        },
    )
