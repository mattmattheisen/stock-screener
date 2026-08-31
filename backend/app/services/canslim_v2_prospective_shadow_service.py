"""Prospective-only CAN SLIM V1-vs-V2 shadow evidence collection.

This service deliberately refuses historical reconstruction. It prepares a
current cached snapshot, requires the stock and benchmark bars to end on the
requested date, requires an exact persisted Market Exposure row, and requires
an exact-date canonical Market RS publication before the existing shadow batch
evaluator may persist any comparison evidence.

No provider fallback, scheduling, scan registration, or transaction commit is
owned by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping, Protocol, Sequence

import pandas as pd
from sqlalchemy.orm import Session

from app.domain.scanning.ports import (
    CanonicalMarketRsSource,
    MarketRsReader,
    StockDataProvider,
)
from app.models.market_exposure import MarketExposure
from app.scanners.base_screener import DataRequirements, StockData
from app.scanners.canslim_scanner import CANSLIMScanner
from app.scanners.canslim_v2_scanner import CANSLIMV2Scanner
from app.services.benchmark_resolution import benchmark_remote_fetch_disabled
from app.services.canslim_v2_shadow_batch_service import (
    CANSLIMV2ShadowBatchEvaluator,
    CANSLIMV2ShadowBatchResult,
    CANSLIMV2ShadowContext,
)


class ProspectiveShadowIntegrityError(RuntimeError):
    """The requested point-in-time shadow snapshot is not internally coherent."""


class MarketExposureSnapshotUnavailable(LookupError):
    """No exact persisted Market Exposure row exists for the requested date."""


@dataclass(frozen=True)
class MarketExposureSnapshot:
    market: str
    as_of_date: date
    exposure_score: float
    stance: str


class MarketExposureSnapshotReader(Protocol):
    def get_exact(
        self,
        *,
        market: str,
        as_of_date: date,
    ) -> MarketExposureSnapshot: ...


class ShadowBatchEvaluator(Protocol):
    def evaluate_and_persist_batch(
        self,
        *,
        symbols: Sequence[str],
        data_by_symbol: Mapping[str, StockData],
        context_by_symbol: Mapping[str, CANSLIMV2ShadowContext],
        as_of_date: date,
        run_ref: str,
    ) -> CANSLIMV2ShadowBatchResult: ...


class SqlMarketExposureSnapshotReader:
    """Read one exact-date persisted Market Exposure snapshot."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def get_exact(
        self,
        *,
        market: str,
        as_of_date: date,
    ) -> MarketExposureSnapshot:
        normalized_market = str(market or "").strip().upper()
        if not normalized_market:
            raise ValueError("market is required")
        db = self._session_factory()
        try:
            row = (
                db.query(MarketExposure)
                .filter(
                    MarketExposure.market == normalized_market,
                    MarketExposure.date == as_of_date,
                )
                .one_or_none()
            )
            if row is None:
                raise MarketExposureSnapshotUnavailable(
                    f"Market Exposure is unavailable for {normalized_market} on "
                    f"{as_of_date.isoformat()}"
                )
            return MarketExposureSnapshot(
                market=normalized_market,
                as_of_date=row.date,
                exposure_score=float(row.exposure_score),
                stance=str(row.stance),
            )
        finally:
            db.close()


@dataclass(frozen=True)
class CANSLIMV2ProspectiveShadowResult:
    """Audit metadata plus the persisted batch result for one prospective run."""

    market: str
    as_of_date: date
    run_ref: str
    market_exposure_score: float
    market_stance: str
    market_rs_formula_version: str
    market_rs_run_id: int
    market_rs_universe_size: int
    batch_result: CANSLIMV2ShadowBatchResult


class CANSLIMV2ProspectiveShadowCollector:
    """Collect one exact-date, cache-only prospective V1-vs-V2 shadow batch."""

    def __init__(
        self,
        *,
        stock_data_provider: StockDataProvider,
        market_rs_reader: MarketRsReader,
        market_exposure_reader: MarketExposureSnapshotReader,
        batch_evaluator: ShadowBatchEvaluator,
    ) -> None:
        self._stock_data_provider = stock_data_provider
        self._market_rs_reader = market_rs_reader
        self._market_exposure_reader = market_exposure_reader
        self._batch_evaluator = batch_evaluator

    def collect(
        self,
        *,
        symbols: Sequence[str],
        as_of_date: date,
        run_ref: str,
        market: str = "US",
        group_rank_by_symbol: Mapping[str, int | None] | None = None,
        catalyst_recent_by_symbol: Mapping[str, bool | None] | None = None,
    ) -> CANSLIMV2ProspectiveShadowResult:
        """Prepare, validate, and persist a prospective comparison batch.

        The caller owns the surrounding database transaction. No evidence is
        evaluated until every stock, benchmark, M snapshot, and canonical RS
        publication has passed the point-in-time integrity checks.
        """

        normalized_market = str(market or "").strip().upper()
        if not normalized_market:
            raise ValueError("market is required")
        normalized_run_ref = str(run_ref or "").strip()
        if not normalized_run_ref:
            raise ValueError("run_ref is required")
        requested_symbols = self._normalize_symbols(symbols)

        exposure = self._market_exposure_reader.get_exact(
            market=normalized_market,
            as_of_date=as_of_date,
        )
        if (
            exposure.market != normalized_market
            or exposure.as_of_date != as_of_date
        ):
            raise ProspectiveShadowIntegrityError(
                "Market Exposure reader returned a snapshot with the wrong identity"
            )

        requirements = self._requirements()
        # Prices/fundamentals already have batch-only controls. The benchmark
        # guard closes the last remote-provider path for the same execution.
        with benchmark_remote_fetch_disabled():
            prepared = self._stock_data_provider.prepare_data_bulk(
                list(requested_symbols),
                requirements,
                allow_partial=False,
                batch_only_prices=True,
                batch_only_fundamentals=True,
            )

        data_by_symbol, canonical_symbols = self._validate_prepared_snapshot(
            requested_symbols=requested_symbols,
            prepared=prepared,
            market=normalized_market,
            as_of_date=as_of_date,
        )

        resolution = self._market_rs_reader.get(
            market=normalized_market,
            symbols=canonical_symbols,
            as_of_date=as_of_date,
        )
        if not isinstance(resolution.source, CanonicalMarketRsSource):
            raise ProspectiveShadowIntegrityError(
                "Prospective CAN SLIM shadow collection requires canonical Market RS"
            )
        if resolution.as_of_date != as_of_date:
            raise ProspectiveShadowIntegrityError(
                "Canonical Market RS publication date does not match the requested date"
            )
        missing_rs = [
            symbol
            for symbol in canonical_symbols
            if symbol not in resolution.ratings_by_symbol
        ]
        if missing_rs:
            raise ProspectiveShadowIntegrityError(
                "Canonical Market RS is missing requested symbols: "
                + ", ".join(missing_rs)
            )

        self._stock_data_provider.apply_market_rs_resolution(
            data_by_symbol,
            resolution,
        )

        group_ranks = self._normalize_optional_mapping(
            group_rank_by_symbol,
            allowed_symbols=set(canonical_symbols),
            label="group rank",
        )
        catalysts = self._normalize_optional_mapping(
            catalyst_recent_by_symbol,
            allowed_symbols=set(canonical_symbols),
            label="catalyst",
        )
        context_by_symbol = {
            symbol: CANSLIMV2ShadowContext(
                market_exposure_score=exposure.exposure_score,
                group_rank=group_ranks.get(symbol),
                catalyst_recent=catalysts.get(symbol),
            )
            for symbol in canonical_symbols
        }

        batch_result = self._batch_evaluator.evaluate_and_persist_batch(
            symbols=canonical_symbols,
            data_by_symbol=data_by_symbol,
            context_by_symbol=context_by_symbol,
            as_of_date=as_of_date,
            run_ref=normalized_run_ref,
        )

        return CANSLIMV2ProspectiveShadowResult(
            market=normalized_market,
            as_of_date=as_of_date,
            run_ref=normalized_run_ref,
            market_exposure_score=exposure.exposure_score,
            market_stance=exposure.stance,
            market_rs_formula_version=resolution.formula_version,
            market_rs_run_id=int(resolution.run_id),
            market_rs_universe_size=int(resolution.universe_size),
            batch_result=batch_result,
        )

    @staticmethod
    def _requirements() -> DataRequirements:
        return CANSLIMScanner().get_data_requirements().merge(
            CANSLIMV2Scanner().get_data_requirements()
        )

    @staticmethod
    def _normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_symbol in symbols:
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol:
                raise ValueError("symbols must be non-empty")
            if symbol in seen:
                raise ValueError(
                    f"duplicate prospective shadow symbol after normalization: {symbol}"
                )
            seen.add(symbol)
            normalized.append(symbol)
        if not normalized:
            raise ValueError("at least one symbol is required")
        return tuple(normalized)

    @classmethod
    def _validate_prepared_snapshot(
        cls,
        *,
        requested_symbols: tuple[str, ...],
        prepared: Mapping[str, object],
        market: str,
        as_of_date: date,
    ) -> tuple[dict[str, StockData], tuple[str, ...]]:
        prepared_by_request = {
            str(key).strip().upper(): value for key, value in prepared.items()
        }
        missing = [
            symbol for symbol in requested_symbols if symbol not in prepared_by_request
        ]
        if missing:
            raise ProspectiveShadowIntegrityError(
                "Cache-only preparation omitted requested symbols: "
                + ", ".join(missing)
            )

        data_by_symbol: dict[str, StockData] = {}
        canonical_symbols: list[str] = []
        for requested_symbol in requested_symbols:
            raw_data = prepared_by_request[requested_symbol]
            if not isinstance(raw_data, StockData):
                raise ProspectiveShadowIntegrityError(
                    f"Prepared data for {requested_symbol} is not StockData"
                )
            stock_data = raw_data
            canonical_symbol = str(stock_data.symbol or "").strip().upper()
            if not canonical_symbol:
                raise ProspectiveShadowIntegrityError(
                    f"Prepared data for {requested_symbol} has no canonical symbol"
                )
            if canonical_symbol in data_by_symbol:
                raise ProspectiveShadowIntegrityError(
                    f"Multiple requested symbols resolve to {canonical_symbol}"
                )
            stock_market = str(stock_data.market or "US").strip().upper()
            if stock_market != market:
                raise ProspectiveShadowIntegrityError(
                    f"{canonical_symbol} resolved to market {stock_market}, expected {market}"
                )
            if stock_data.fetch_errors:
                raise ProspectiveShadowIntegrityError(
                    f"{canonical_symbol} contains fetch errors: "
                    + stock_data.get_error_summary()
                )

            stock_latest = cls._latest_frame_date(stock_data.price_data)
            if stock_latest != as_of_date:
                raise ProspectiveShadowIntegrityError(
                    f"{canonical_symbol} stock snapshot ends on {stock_latest}, "
                    f"expected {as_of_date}"
                )
            benchmark_latest = cls._latest_frame_date(stock_data.benchmark_data)
            if benchmark_latest != as_of_date:
                raise ProspectiveShadowIntegrityError(
                    f"{canonical_symbol} benchmark snapshot ends on {benchmark_latest}, "
                    f"expected {as_of_date}"
                )

            data_by_symbol[canonical_symbol] = stock_data
            canonical_symbols.append(canonical_symbol)

        return data_by_symbol, tuple(canonical_symbols)

    @staticmethod
    def _latest_frame_date(frame: pd.DataFrame | None) -> date | None:
        if frame is None or frame.empty:
            return None
        dates: list[date] = []
        for value in frame.index:
            try:
                timestamp = pd.Timestamp(value)
            except (TypeError, ValueError):
                continue
            if pd.isna(timestamp):
                continue
            dates.append(timestamp.date())
        return max(dates) if dates else None

    @staticmethod
    def _normalize_optional_mapping(
        mapping: Mapping[str, object] | None,
        *,
        allowed_symbols: set[str],
        label: str,
    ) -> dict[str, object]:
        if not mapping:
            return {}
        normalized: dict[str, object] = {}
        for raw_symbol, value in mapping.items():
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol:
                raise ValueError(f"{label} symbol keys must be non-empty")
            if symbol in normalized:
                raise ValueError(
                    f"duplicate {label} symbol after normalization: {symbol}"
                )
            if symbol not in allowed_symbols:
                raise ValueError(f"{label} supplied for unrequested symbol: {symbol}")
            normalized[symbol] = value
        return normalized
