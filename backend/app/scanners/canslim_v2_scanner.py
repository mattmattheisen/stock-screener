"""Unregistered CAN SLIM V2 scanner adapter.

The class intentionally has no ``@register_screener`` decorator. It exists so
V2 can be exercised directly and validated against V1 before it becomes a
production-selectable screener.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from .base_screener import (
    BaseStockScreener,
    DataRequirements,
    ScreenerResult,
    StockData,
)
from .criteria.canslim_v2 import CANSLIMLetter
from .criteria.canslim_v2_adapter import extract_v2_inputs, evaluate_v2_inputs
from .criteria.relative_strength import RelativeStrengthCalculator
from .criteria.rs_resolution import CanonicalStockRsUnavailable, resolve_stock_rs

logger = logging.getLogger(__name__)


class CANSLIMV2Scanner(BaseStockScreener):
    """Deterministic CAN SLIM V2 scanner, intentionally unregistered."""

    def __init__(self) -> None:
        self.rs_calc = RelativeStrengthCalculator()

    @property
    def screener_name(self) -> str:
        return "canslim_v2"

    def get_data_requirements(
        self,
        criteria: Optional[Dict] = None,
    ) -> DataRequirements:
        """Reuse fundamentals/quarterly/benchmark data already fetched by V1."""

        return DataRequirements(
            price_period="2y",
            needs_fundamentals=True,
            needs_quarterly_growth=True,
            needs_benchmark=True,
            needs_earnings_history=False,
        )

    def scan_stock(
        self,
        symbol: str,
        data: StockData,
        criteria: Optional[Dict] = None,
    ) -> ScreenerResult:
        """Evaluate a stock with V2 without registering it in production."""

        try:
            if not data.has_sufficient_data(min_days=240):
                return self._insufficient_data_result("Insufficient price data")

            precomputed = data.precomputed_scan_context
            price_data = data.price_data
            benchmark_data = data.benchmark_data

            prices_chrono = (
                precomputed.close_chrono
                if precomputed is not None and precomputed.close_chrono is not None
                else price_data["Close"].reset_index(drop=True)
            )
            spy_prices_chrono = (
                precomputed.benchmark_close_chrono
                if (
                    precomputed is not None
                    and precomputed.benchmark_close_chrono is not None
                )
                else benchmark_data["Close"].reset_index(drop=True)
            )
            prices = (
                precomputed.close_rev
                if precomputed is not None and precomputed.close_rev is not None
                else prices_chrono[::-1].reset_index(drop=True)
            )
            spy_prices = (
                precomputed.benchmark_close_rev
                if (
                    precomputed is not None
                    and precomputed.benchmark_close_rev is not None
                )
                else spy_prices_chrono[::-1].reset_index(drop=True)
            )

            rs_ratings = (
                precomputed.rs_ratings
                if (
                    precomputed is not None
                    and precomputed.rs_ratings is not None
                )
                else resolve_stock_rs(
                    data,
                    lambda: self.rs_calc.calculate_all_rs_ratings(
                        symbol,
                        prices,
                        spy_prices,
                        data.rs_universe_performances,
                    ),
                )
            )

            context = criteria or {}
            inputs = extract_v2_inputs(
                data,
                rs_rating=rs_ratings.get("rs_rating"),
                market_exposure_score=context.get("market_exposure_score"),
                group_rank=context.get("group_rank"),
                catalyst_recent=context.get("catalyst_recent"),
            )
            scorecard = evaluate_v2_inputs(inputs)
            criteria_by_letter = scorecard.criteria

            breakdown = {
                "current_earnings": criteria_by_letter[
                    CANSLIMLetter.CURRENT_EARNINGS
                ].points,
                "annual_earnings": criteria_by_letter[
                    CANSLIMLetter.ANNUAL_EARNINGS
                ].points,
                "new_highs": criteria_by_letter[CANSLIMLetter.NEW].points,
                "supply_demand": criteria_by_letter[
                    CANSLIMLetter.SUPPLY_DEMAND
                ].points,
                "leader": criteria_by_letter[CANSLIMLetter.LEADER].points,
                "institutional": criteria_by_letter[
                    CANSLIMLetter.INSTITUTIONAL
                ].points,
            }

            details = {
                "methodology_version": scorecard.methodology_version,
                "status": scorecard.status,
                "stock_passes": scorecard.stock_passes,
                "market_passes": scorecard.market_passes,
                "actionable": scorecard.actionable,
                "market": criteria_by_letter[CANSLIMLetter.MARKET].as_dict(),
                "rs_rating": inputs.rs_rating,
                "rs_rating_1m": rs_ratings.get("rs_rating_1m"),
                "rs_rating_3m": rs_ratings.get("rs_rating_3m"),
                "rs_rating_12m": rs_ratings.get("rs_rating_12m"),
                "full_analysis": scorecard.as_dict(),
            }

            return ScreenerResult(
                score=scorecard.stock_score,
                passes=scorecard.actionable,
                rating=self.calculate_rating(scorecard.stock_score, details),
                breakdown=breakdown,
                details=details,
                screener_name=self.screener_name,
            )

        except CanonicalStockRsUnavailable as exc:
            return self._insufficient_data_result(str(exc))
        except Exception as exc:
            logger.error("Error scanning %s with CANSLIM V2: %s", symbol, exc)
            return self._error_result(str(exc))

    def calculate_rating(self, score: float, details: Dict) -> str:
        """Translate scorecard state without allowing score to override M."""

        status = details.get("status")
        if status == "qualified":
            return "Strong Buy" if score >= 85.0 else "Buy"
        if status == "market_blocked":
            return "Market Blocked"
        if status == "market_unknown":
            return "Market Unknown"
        if status == "insufficient_data":
            return "Insufficient Data"
        if status == "watchlist":
            return "Watch"
        return "Pass"

    def _insufficient_data_result(self, reason: str) -> ScreenerResult:
        return ScreenerResult(
            score=0.0,
            passes=False,
            rating="Insufficient Data",
            breakdown={},
            details={"error": reason, "methodology_version": "canslim_v2"},
            screener_name=self.screener_name,
        )

    def _error_result(self, error: str) -> ScreenerResult:
        return ScreenerResult(
            score=0.0,
            passes=False,
            rating="Error",
            breakdown={},
            details={
                "error": f"Scan error: {error}",
                "methodology_version": "canslim_v2",
            },
            screener_name=self.screener_name,
        )
