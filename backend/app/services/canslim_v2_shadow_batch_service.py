"""Strict batch runner for prospective CAN SLIM V1-vs-V2 shadow evidence.

The runner accepts only already-prefetched ``StockData`` objects. It performs no
provider calls and validates the complete requested batch before evaluating any
symbol, preventing partial or fallback-contaminated evidence collection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Protocol, Sequence

from app.scanners.base_screener import StockData
from app.services.canslim_v2_shadow_service import CANSLIMV2ShadowPersistenceResult


@dataclass(frozen=True)
class CANSLIMV2ShadowContext:
    """Point-in-time non-StockData context required by CAN SLIM V2."""

    market_exposure_score: float | None
    group_rank: int | None = None
    catalyst_recent: bool | None = None


@dataclass(frozen=True)
class CANSLIMV2ShadowBatchResult:
    """Summary and ordered results for one complete shadow batch."""

    run_ref: str
    as_of_date: date
    results: tuple[CANSLIMV2ShadowPersistenceResult, ...]

    @property
    def requested(self) -> int:
        return len(self.results)

    @property
    def created(self) -> int:
        return sum(1 for result in self.results if result.created)

    @property
    def reused(self) -> int:
        return self.requested - self.created


class ShadowEvaluator(Protocol):
    def evaluate_and_persist(
        self,
        *,
        symbol: str,
        data: StockData,
        as_of_date: date,
        run_ref: str,
        market_exposure_score: float | None,
        group_rank: int | None = None,
        catalyst_recent: bool | None = None,
    ) -> CANSLIMV2ShadowPersistenceResult: ...


class CANSLIMV2ShadowBatchEvaluator:
    """Evaluate a complete, already-prefetched batch without fallback fetching."""

    def __init__(self, evaluator: ShadowEvaluator) -> None:
        self._evaluator = evaluator

    def evaluate_and_persist_batch(
        self,
        *,
        symbols: Sequence[str],
        data_by_symbol: Mapping[str, StockData],
        context_by_symbol: Mapping[str, CANSLIMV2ShadowContext],
        as_of_date: date,
        run_ref: str,
    ) -> CANSLIMV2ShadowBatchResult:
        """Persist evidence for every requested symbol or for none of them.

        Validation happens before the first evaluator call. The service does not
        own transaction commit/rollback; callers should place a repository backed
        evaluator inside their normal transaction boundary.
        """

        normalized_run_ref = str(run_ref).strip()
        if not normalized_run_ref:
            raise ValueError("run_ref is required for shadow batch persistence")

        normalized_symbols = self._normalize_requested_symbols(symbols)
        normalized_data = self._normalize_mapping(data_by_symbol, "data")
        normalized_context = self._normalize_mapping(context_by_symbol, "context")

        missing_data = [symbol for symbol in normalized_symbols if symbol not in normalized_data]
        if missing_data:
            raise ValueError(
                "shadow batch requires complete prefetch; missing data for: "
                + ", ".join(missing_data)
            )

        missing_context = [
            symbol for symbol in normalized_symbols if symbol not in normalized_context
        ]
        if missing_context:
            raise ValueError(
                "shadow batch requires complete point-in-time context; missing: "
                + ", ".join(missing_context)
            )

        for symbol in normalized_symbols:
            stock_data = normalized_data[symbol]
            data_symbol = str(getattr(stock_data, "symbol", "")).strip().upper()
            if data_symbol != symbol:
                raise ValueError(
                    f"shadow batch data identity mismatch for {symbol}: "
                    f"StockData.symbol={data_symbol or '<empty>'}"
                )

        results: list[CANSLIMV2ShadowPersistenceResult] = []
        for symbol in normalized_symbols:
            context = normalized_context[symbol]
            results.append(
                self._evaluator.evaluate_and_persist(
                    symbol=symbol,
                    data=normalized_data[symbol],
                    as_of_date=as_of_date,
                    run_ref=normalized_run_ref,
                    market_exposure_score=context.market_exposure_score,
                    group_rank=context.group_rank,
                    catalyst_recent=context.catalyst_recent,
                )
            )

        return CANSLIMV2ShadowBatchResult(
            run_ref=normalized_run_ref,
            as_of_date=as_of_date,
            results=tuple(results),
        )

    @staticmethod
    def _normalize_requested_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_symbol in symbols:
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                raise ValueError("shadow batch symbols must be non-empty")
            if symbol in seen:
                raise ValueError(f"duplicate shadow batch symbol after normalization: {symbol}")
            seen.add(symbol)
            normalized.append(symbol)
        if not normalized:
            raise ValueError("shadow batch requires at least one symbol")
        return tuple(normalized)

    @staticmethod
    def _normalize_mapping(mapping: Mapping[str, object], label: str) -> dict[str, object]:
        normalized: dict[str, object] = {}
        for raw_symbol, value in mapping.items():
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                raise ValueError(f"shadow batch {label} keys must be non-empty")
            if symbol in normalized:
                raise ValueError(
                    f"duplicate shadow batch {label} key after normalization: {symbol}"
                )
            normalized[symbol] = value
        return normalized
