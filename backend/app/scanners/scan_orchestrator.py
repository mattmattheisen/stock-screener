"""
Scan orchestrator for multi-screener coordination.

Coordinates running multiple screeners on a single stock, with data
fetched once and shared across all screeners. Combines results and
calculates composite scores.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from app.analysis.patterns.config import (
    build_setup_engine_parameters,
)
from app.analysis.patterns.rs_line import (
    DEFAULT_BLUE_DOT_RECENT_DAYS,
    DEFAULT_LOOKBACK,
    RsLineLeadershipSnapshot,
    rs_line_leadership_snapshot,
)
from app.config import settings
from app.domain.scanning.models import CompositeMethod, ScreenerOutputDomain
from app.domain.scanning.ports import (
    CanonicalStockRsSource,
    MarketRsReader,
    MarketRsResolution,
    StockDataProvider,
)
from app.domain.scanning.scoring import (
    apply_quality_policy,
    calculate_composite_score,
    calculate_overall_rating,
)
from app.services.opportunity_state_service import (
    build_data_limited_projection,
)

from .base_screener import (
    BaseStockScreener,
    DataRequirements,
    PrecomputedScanContext,
    ScreenerResult,
    StockData,
)
from .criteria.relative_strength import RelativeStrengthCalculator
from .criteria.rs_resolution import CanonicalStockRsUnavailable, resolve_stock_rs
from .partial_history_metrics import partial_history_metrics
from .scan_result_assembler import (
    ScanResultAssembler,
    ScanResultAssemblyRequest,
    market_rs_audit_fields,
)
from .screener_registry import ScreenerRegistry

logger = logging.getLogger(__name__)

LISTING_ONLY_MIN_BARS = 30
FULL_SCAN_MIN_BARS = 252
IPO_BONUS_MIN_SCORE = 60.0
IPO_BONUS_MAX = 15.0
_DEFAULT_SCREENER_MIN_BARS = 100
_SCREENER_MIN_BARS: dict[str, int] = {
    "ipo": 30,
    "setup_engine": 100,
    "custom": 200,
    "minervini": 240,
    "canslim": 240,
    "volume_breakthrough": 252,
}


def _series_last_float(series) -> float | None:
    if series is None or len(series) == 0:
        return None
    value = series.iloc[-1]
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    return float(value)


def _build_precomputed_scan_context(
    stock_data: StockData,
) -> PrecomputedScanContext | None:
    """Build shared derived scan metrics once per symbol."""
    price_data = stock_data.price_data
    if price_data is None or price_data.empty or "Close" not in price_data.columns:
        return None

    close_indexed = price_data["Close"]
    close_chrono = close_indexed.reset_index(drop=True)
    close_rev = close_chrono[::-1].reset_index(drop=True)

    volume_chrono = None
    volume_rev = None
    if "Volume" in price_data.columns:
        volume_chrono = price_data["Volume"].reset_index(drop=True)
        volume_rev = volume_chrono[::-1].reset_index(drop=True)

    benchmark_close_indexed = None
    benchmark_close_chrono = None
    benchmark_close_rev = None
    if (
        stock_data.benchmark_data is not None
        and not stock_data.benchmark_data.empty
        and "Close" in stock_data.benchmark_data.columns
    ):
        benchmark_close_indexed = stock_data.benchmark_data["Close"]
        benchmark_close_chrono = benchmark_close_indexed.reset_index(drop=True)
        benchmark_close_rev = benchmark_close_chrono[::-1].reset_index(drop=True)

    ma_50_series = close_chrono.rolling(window=50, min_periods=50).mean()
    ma_150_series = close_chrono.rolling(window=150, min_periods=150).mean()
    ma_200_series = close_chrono.rolling(window=200, min_periods=200).mean()
    ema_10_series = close_chrono.ewm(span=10, adjust=False).mean()
    ema_20_series = close_chrono.ewm(span=20, adjust=False).mean()
    ema_50_series = close_chrono.ewm(span=50, adjust=False).mean()

    ma_200_month_ago = None
    if len(ma_200_series) > 220:
        ma_200_month_ago = _series_last_float(ma_200_series.iloc[:-20])
    if ma_200_month_ago is None:
        ma_200_month_ago = _series_last_float(ma_200_series)

    rs_ratings = None
    if isinstance(stock_data.rs_source, CanonicalStockRsSource) or (
        benchmark_close_rev is not None and not benchmark_close_rev.empty
    ):
        rs_ratings = resolve_stock_rs(
            stock_data,
            lambda: RelativeStrengthCalculator().calculate_all_rs_ratings(
                stock_data.symbol,
                close_rev,
                benchmark_close_rev,
                stock_data.rs_universe_performances,
            ),
        )

    rs_leadership = RsLineLeadershipSnapshot.empty()
    if benchmark_close_indexed is not None and not benchmark_close_indexed.empty:
        rs_leadership = rs_line_leadership_snapshot(
            close_indexed,
            benchmark_close_indexed,
            lookback=DEFAULT_LOOKBACK,
            recent_days=DEFAULT_BLUE_DOT_RECENT_DAYS,
        )

    return PrecomputedScanContext(
        close_chrono=close_chrono,
        close_rev=close_rev,
        volume_chrono=volume_chrono,
        volume_rev=volume_rev,
        benchmark_close_chrono=benchmark_close_chrono,
        benchmark_close_rev=benchmark_close_rev,
        current_price=_series_last_float(close_chrono),
        ma_50=_series_last_float(ma_50_series),
        ma_150=_series_last_float(ma_150_series),
        ma_200=_series_last_float(ma_200_series),
        ma_200_month_ago=ma_200_month_ago,
        ema_10=_series_last_float(ema_10_series),
        ema_20=_series_last_float(ema_20_series),
        ema_50=_series_last_float(ema_50_series),
        high_52w=float(close_rev.max()) if not close_rev.empty else None,
        low_52w=float(close_rev.min()) if not close_rev.empty else None,
        rs_ratings=rs_ratings,
        rs_line_leadership=rs_leadership,
    )


def _to_domain_output(name: str, result: ScreenerResult) -> ScreenerOutputDomain:
    """Map an infrastructure ScreenerResult to a domain ScreenerOutputDomain."""
    return ScreenerOutputDomain(
        screener_name=name,
        score=result.score,
        passes=result.passes,
        rating=result.rating,
        breakdown=result.breakdown,
        details=result.details,
    )


def _history_bar_count(stock_data: StockData) -> int:
    price_data = stock_data.price_data
    if price_data is None or getattr(price_data, "empty", True):
        return 0
    return len(price_data)


def _required_bars_for_screener(name: str) -> int:
    return _SCREENER_MIN_BARS.get(name, _DEFAULT_SCREENER_MIN_BARS)


def _requirements_with_rs_line_fields(
    requirements: DataRequirements,
) -> DataRequirements:
    """Row-level RS leadership fields need benchmark data for every scan row."""
    if requirements.needs_benchmark:
        return requirements
    return DataRequirements(
        price_period=requirements.price_period,
        needs_fundamentals=requirements.needs_fundamentals,
        needs_quarterly_growth=requirements.needs_quarterly_growth,
        needs_benchmark=True,
        needs_earnings_history=requirements.needs_earnings_history,
    )


def _compute_ipo_bonus(ipo_score: float | None, history_bars: int) -> float:
    if (
        ipo_score is None
        or ipo_score < IPO_BONUS_MIN_SCORE
        or history_bars < LISTING_ONLY_MIN_BARS
        or history_bars >= FULL_SCAN_MIN_BARS
    ):
        return 0.0
    raw_bonus = IPO_BONUS_MAX * (
        (FULL_SCAN_MIN_BARS - history_bars)
        / (FULL_SCAN_MIN_BARS - LISTING_ONLY_MIN_BARS)
    )
    return round(max(0.0, raw_bonus), 2)


def _scan_mode_for_history(history_bars: int) -> str:
    if history_bars >= FULL_SCAN_MIN_BARS:
        return "full"
    if history_bars >= LISTING_ONLY_MIN_BARS:
        return "ipo_weighted"
    return "listing_only"


def _insufficient_screener_reason(
    insufficient_screeners: dict[str, str | None],
) -> str:
    parts: list[str] = []
    for name in sorted(insufficient_screeners):
        reason = insufficient_screeners[name]
        parts.append(f"{name} ({reason})" if reason else name)
    return "Insufficient data from runnable screeners: " + ", ".join(parts)


class ScanOrchestrator:
    """
    Orchestrates multi-screener stock analysis.

    Coordinates:
    1. Getting screeners from registry
    2. Merging data requirements
    3. Fetching data once
    4. Running all screeners
    5. Combining results
    """

    def __init__(
        self,
        data_provider: StockDataProvider,
        registry: ScreenerRegistry,
        market_rs_reader: MarketRsReader | None = None,
        result_assembler: ScanResultAssembler | None = None,
    ):
        """Initialize orchestrator with injected dependencies.

        Args:
            data_provider: Port for fetching stock data
            registry: Registry of available screeners
        """
        self._data_provider = data_provider
        self._registry = registry
        self._market_rs_reader = market_rs_reader
        self._result_assembler = result_assembler or ScanResultAssembler()

    def get_merged_requirements(
        self,
        screener_names: List[str],
        criteria: Optional[Dict] = None,
    ) -> DataRequirements:
        """Merge data requirements once for a screener set (batch optimization)."""
        if not settings.setup_engine_enabled:
            screener_names = [n for n in screener_names if n != "setup_engine"]
        if not screener_names:
            return DataRequirements()

        screeners = self._registry.get_multiple(screener_names)
        return _requirements_with_rs_line_fields(
            DataRequirements.merge_all([
                screener.get_data_requirements(criteria)
                for screener in screeners.values()
            ])
        )

    def scan_stock_multi(
        self,
        symbol: str,
        screener_names: List[str],
        criteria: Optional[Dict] = None,
        composite_method: str = "weighted_average",
        pre_merged_requirements: Optional[DataRequirements] = None,
        pre_fetched_data: Optional[StockData] = None,
        market_rs_resolution: MarketRsResolution | None = None,
    ) -> Dict:
        """
        Run multiple screeners on a single stock.

        Args:
            symbol: Stock symbol
            screener_names: List of screener names to run
            criteria: Optional criteria/parameters for screeners
            composite_method: How to combine scores (weighted_average, maximum, minimum)
            pre_merged_requirements: Optional pre-merged requirements (batch optimization)
            pre_fetched_data: Optional pre-fetched stock data (batch optimization)
            market_rs_resolution: Optional publication pinned by the calling workflow

        Returns:
            Dict with combined results from all screeners
        """
        try:
            # Parse composite_method string defensively
            try:
                method_enum = CompositeMethod(composite_method)
            except ValueError:
                logger.warning("Unknown composite method '%s', defaulting to weighted_average", composite_method)
                method_enum = CompositeMethod.WEIGHTED_AVERAGE

            # 1. Filter disabled screeners (silent — no per-symbol warning)
            if not settings.setup_engine_enabled:
                screener_names = [n for n in screener_names if n != "setup_engine"]
            if not screener_names:
                return {
                    "symbol": symbol,
                    "composite_score": 0,
                    "rating": "Error",
                    "error": "All requested screeners are disabled",
                    "current_price": None,
                    "screeners_run": [],
                }

            # 2. Get screener instances from registry
            try:
                screeners = self._registry.get_multiple(screener_names)
            except ValueError as e:
                logger.error(f"Error getting screeners: {e}")
                return self._error_result(symbol, str(e))

            # 2. Get stock data (use pre-fetched if available)
            if pre_fetched_data:
                # Use pre-fetched data from batch processing (NO rate limiting!)
                stock_data = pre_fetched_data
                logger.debug(f"Using pre-fetched data for {symbol}")
            else:
                # Merge requirements and fetch data (legacy path)
                if pre_merged_requirements:
                    requirements = _requirements_with_rs_line_fields(pre_merged_requirements)
                    logger.debug(f"Using pre-merged requirements for {symbol}")
                else:
                    requirements = _requirements_with_rs_line_fields(
                        DataRequirements.merge_all([
                            screener.get_data_requirements(criteria)
                            for screener in screeners.values()
                        ])
                    )
                    logger.info(f"Merged data requirements for {symbol}: {requirements}")

                # Fetch data ONCE
                stock_data = self._data_provider.prepare_data(symbol, requirements)

            if stock_data.rs_source is None and market_rs_resolution is not None:
                self._data_provider.apply_market_rs_resolution(
                    {stock_data.symbol.strip().upper(): stock_data},
                    market_rs_resolution,
                )
            elif stock_data.rs_source is None and self._market_rs_reader is not None:
                resolution = self._market_rs_reader.get(
                    market=str(stock_data.market or "US").strip().upper(),
                    symbols=(stock_data.symbol.strip().upper(),),
                    as_of_date=None,
                    formula_version=None,
                )
                self._data_provider.apply_market_rs_resolution(
                    {stock_data.symbol.strip().upper(): stock_data}, resolution
                )

            history_bars = _history_bar_count(stock_data)

            if stock_data.precomputed_scan_context is None and history_bars > 0:
                try:
                    stock_data.precomputed_scan_context = _build_precomputed_scan_context(stock_data)
                except CanonicalStockRsUnavailable as exc:
                    return self._insufficient_data_result(
                        symbol,
                        stock_data,
                        composite_method=composite_method,
                        history_bars=history_bars,
                        applicable_screeners=[],
                        unavailable_screeners=screener_names,
                        reason=str(exc),
                    )

            unavailable_screeners: list[str] = []
            runnable_screeners: dict[str, BaseStockScreener] = {}
            for name, screener in screeners.items():
                if history_bars < _required_bars_for_screener(name):
                    unavailable_screeners.append(name)
                    continue
                runnable_screeners[name] = screener

            if history_bars < LISTING_ONLY_MIN_BARS or not runnable_screeners:
                return self._insufficient_data_result(
                    symbol,
                    stock_data,
                    composite_method=composite_method,
                    history_bars=history_bars,
                    applicable_screeners=[],
                    unavailable_screeners=screener_names,
                    reason=stock_data.get_error_summary() or "Insufficient price history",
                )

            # 5. Run applicable screeners in parallel on the same data
            screener_results: Dict[str, ScreenerResult] = {}
            hard_error_screeners: list[str] = []
            insufficient_screeners: dict[str, str | None] = {}

            def run_screener(name: str, screener: BaseStockScreener) -> tuple[str, Optional[ScreenerResult]]:
                """Run a single screener and return (name, result) tuple."""
                try:
                    result = screener.scan_stock(symbol, stock_data, criteria)
                    logger.info(
                        f"{symbol} - {name}: score={result.score:.1f}, "
                        f"passes={result.passes}, rating={result.rating}"
                    )
                    return (name, result)
                except Exception as e:
                    logger.error(f"Error running {name} screener on {symbol}: {e}")
                    return (name, None)

            # Execute screeners in parallel (max 5 workers for 5 screeners)
            with ThreadPoolExecutor(max_workers=min(len(runnable_screeners), 5)) as executor:
                # Submit all screener tasks
                futures = {
                    executor.submit(run_screener, name, screener): name
                    for name, screener in runnable_screeners.items()
                }

                # Collect results as they complete
                for future in as_completed(futures):
                    name, result = future.result()
                    if result is None:
                        hard_error_screeners.append(name)
                    elif result.rating == "Insufficient Data":
                        unavailable_screeners.append(name)
                        details = result.details if isinstance(result.details, dict) else {}
                        insufficient_screeners[name] = (
                            details.get("reason")
                            or details.get("error")
                        )
                    else:
                        screener_results[name] = result

            if hard_error_screeners:
                failed_screeners = ", ".join(sorted(hard_error_screeners))
                return self._error_result(
                    symbol,
                    f"Screener execution failed: {failed_screeners}",
                )

            if insufficient_screeners:
                return self._insufficient_data_result(
                    symbol,
                    stock_data,
                    composite_method=composite_method,
                    history_bars=history_bars,
                    applicable_screeners=[
                        name for name in screener_names if name in screener_results
                    ],
                    unavailable_screeners=[
                        name for name in screener_names if name in unavailable_screeners
                    ],
                    reason=_insufficient_screener_reason(insufficient_screeners),
                )

            if not screener_results:
                return self._insufficient_data_result(
                    symbol,
                    stock_data,
                    composite_method=composite_method,
                    history_bars=history_bars,
                    applicable_screeners=[],
                    unavailable_screeners=screener_names,
                    reason=stock_data.get_error_summary() or "Insufficient data for applicable screeners",
                )

            # 6. Calculate composite score using domain functions
            domain_outputs = {name: _to_domain_output(name, r) for name, r in screener_results.items()}
            composite_score = calculate_composite_score(domain_outputs, method_enum)
            ipo_score = screener_results.get("ipo").score if screener_results.get("ipo") is not None else None
            ipo_bonus = _compute_ipo_bonus(ipo_score, history_bars)
            composite_reason = None
            scan_mode = "full"
            data_status = "complete"
            if history_bars < FULL_SCAN_MIN_BARS:
                scan_mode = _scan_mode_for_history(history_bars)
                data_status = "insufficient_history"
                if ipo_bonus > 0:
                    composite_score = min(100.0, composite_score + ipo_bonus)
                    composite_reason = "ipo_uplift"

            # 7. Determine overall rating
            rating_category = calculate_overall_rating(composite_score, domain_outputs)

            # 7b. Apply quality-aware fallback (T4): low completeness scores
            #     downgrade or exclude the rating. Tie-break behaviour is
            #     documented in scoring.py; we expose field_completeness_score
            #     in the result so consumers can use it as a secondary sort.
            completeness = None
            if stock_data.fundamentals:
                completeness = stock_data.fundamentals.get(
                    "field_completeness_score"
                )
            adjustment = apply_quality_policy(rating_category, completeness)
            overall_rating = adjustment.rating.value

            # 8. Combine results
            opportunity_parameters = build_setup_engine_parameters(
                (criteria or {}).get("setup_engine_parameters")
            )
            combined_result = self._result_assembler.assemble(
                ScanResultAssemblyRequest(
                    symbol=symbol,
                    stock_data=stock_data,
                    screener_results=screener_results,
                    composite_score=composite_score,
                    overall_rating=overall_rating,
                    composite_method=composite_method,
                    applicable_screeners=tuple(
                        name
                        for name in screener_names
                        if name in screener_results
                    ),
                    unavailable_screeners=tuple(
                        name
                        for name in screener_names
                        if name in unavailable_screeners
                    ),
                    history_bars=history_bars,
                    scan_mode=scan_mode,
                    data_status=data_status,
                    is_scannable=True,
                    ipo_bonus=ipo_bonus,
                    composite_reason=composite_reason,
                    quality_downgrade_reason=adjustment.reason,
                    field_completeness_score=completeness,
                    opportunity_parameters=opportunity_parameters,
                )
            )
            if data_status == "insufficient_history":
                for key, value in partial_history_metrics(stock_data).items():
                    combined_result.setdefault(key, value)

            return combined_result

        except Exception as e:
            logger.error(f"Error orchestrating scan for {symbol}: {e}")
            return self._error_result(symbol, str(e))

    def _error_result(self, symbol: str, error: str) -> Dict:
        """Return result for errors."""
        return {
            "symbol": symbol,
            "composite_score": 0,
            "rating": "Error",
            "error": f"Scan error: {error}",
            "current_price": None,
            "screeners_run": [],
            "result_status": "error",
            "data_status": "error",
            "is_scannable": False,
            "scan_mode": "listing_only",
            "history_bars": 0,
            "applicable_screeners": [],
            "unavailable_screeners": [],
            "composite_reason": None,
            "ipo_bonus": 0.0,
        }

    def _insufficient_data_result(
        self,
        symbol: str,
        stock_data: StockData,
        *,
        composite_method: str,
        history_bars: int,
        applicable_screeners: list[str],
        unavailable_screeners: list[str],
        reason: str,
    ) -> Dict:
        """Return result for insufficient data."""
        result = {
            "symbol": symbol,
            "composite_score": None,
            "rating": "Insufficient Data",
            "reason": reason,
            "current_price": stock_data.get_current_price(),
            "screeners_run": [],
            "composite_method": composite_method,
            "screeners_passed": 0,
            "screeners_total": 0,
            "result_status": "insufficient_history",
            "data_status": "insufficient_history",
            "is_scannable": False,
            "scan_mode": _scan_mode_for_history(history_bars),
            "history_bars": history_bars,
            "applicable_screeners": list(applicable_screeners),
            "unavailable_screeners": list(unavailable_screeners),
            "composite_reason": None,
            "ipo_bonus": 0.0,
            **market_rs_audit_fields(stock_data),
            "details": {
                "screeners": {},
                "data_errors": stock_data.fetch_errors if stock_data.fetch_errors else None,
                **market_rs_audit_fields(stock_data),
            },
        }
        if stock_data.fundamentals:
            if stock_data.fundamentals.get("market_cap") is not None:
                result["market_cap"] = stock_data.fundamentals["market_cap"]
            if stock_data.fundamentals.get("market_cap_usd") is not None:
                result["market_cap_usd"] = stock_data.fundamentals["market_cap_usd"]
            if stock_data.fundamentals.get("eps_rating") is not None:
                result["eps_rating"] = stock_data.fundamentals["eps_rating"]
            if stock_data.fundamentals.get("ipo_date"):
                result["ipo_date"] = stock_data.fundamentals["ipo_date"]
            if stock_data.fundamentals.get("sector"):
                result["gics_sector"] = stock_data.fundamentals["sector"]
            if stock_data.fundamentals.get("industry"):
                result["gics_industry"] = stock_data.fundamentals["industry"]
        result.update(partial_history_metrics(stock_data))
        result.update(
            build_data_limited_projection(result, stock_data, "insufficient_data")
        )
        return result
