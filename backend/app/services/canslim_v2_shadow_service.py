"""Manual same-snapshot CAN SLIM V1-vs-V2 shadow evaluation.

This service is intentionally not wired into scan orchestration. A caller must
supply already-prefetched StockData plus the point-in-time market/group context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Protocol

from app.scanners.base_screener import BaseStockScreener, StockData
from app.scanners.canslim_scanner import CANSLIMScanner
from app.scanners.canslim_v2_scanner import CANSLIMV2Scanner
from app.scanners.canslim_v2_shadow import CANSLIMV2ShadowRecord, build_shadow_record


class ShadowEvidenceRepository(Protocol):
    def save(self, evidence: Mapping[str, Any]) -> tuple[Any, bool]: ...


@dataclass(frozen=True)
class CANSLIMV2ShadowPersistenceResult:
    """Result of one explicit same-snapshot shadow evaluation and write."""

    record: CANSLIMV2ShadowRecord
    persistence_id: int
    created: bool


class CANSLIMV2ShadowEvaluator:
    """Run V1 and V2 on the exact same StockData instance and persist evidence."""

    def __init__(
        self,
        repository: ShadowEvidenceRepository,
        *,
        v1_scanner: BaseStockScreener | None = None,
        v2_scanner: BaseStockScreener | None = None,
    ) -> None:
        self._repository = repository
        self._v1_scanner = v1_scanner or CANSLIMScanner()
        self._v2_scanner = v2_scanner or CANSLIMV2Scanner()

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
    ) -> CANSLIMV2ShadowPersistenceResult:
        """Evaluate both methodologies without any additional data fetches."""

        normalized_run_ref = str(run_ref).strip()
        if not normalized_run_ref:
            raise ValueError("run_ref is required for shadow persistence")

        v1_result = self._v1_scanner.scan_stock(symbol, data)
        v2_result = self._v2_scanner.scan_stock(
            symbol,
            data,
            criteria={
                "market_exposure_score": market_exposure_score,
                "group_rank": group_rank,
                "catalyst_recent": catalyst_recent,
            },
        )
        record = build_shadow_record(
            symbol=symbol,
            v1_result=v1_result,
            v2_result=v2_result,
            as_of_date=as_of_date.isoformat(),
            run_ref=normalized_run_ref,
        )
        row, created = self._repository.save(record.as_dict())
        persistence_id = getattr(row, "id", None)
        if persistence_id is None:
            raise ValueError("shadow repository returned a row without an id")

        return CANSLIMV2ShadowPersistenceResult(
            record=record,
            persistence_id=int(persistence_id),
            created=bool(created),
        )
