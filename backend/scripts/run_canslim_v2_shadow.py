"""Run one prospective, cache-only CAN SLIM V1-vs-V2 shadow collection.

This command is intentionally manual and prospective-only. It refuses remote
provider fallback, requires exact-date stock/benchmark/M/Market-RS evidence,
and rolls the persistence transaction back unless ``--yes`` is supplied.

Usage (from ``backend``)::

    # Evaluate but roll back all shadow rows
    python scripts/run_canslim_v2_shadow.py \
        --symbols AAPL,MSFT,NVDA \
        --as-of-date 2026-08-31 \
        --run-ref manual:2026-08-31:us-growth

    # Persist the exact same evidence
    python scripts/run_canslim_v2_shadow.py \
        --symbols AAPL,MSFT,NVDA \
        --as-of-date 2026-08-31 \
        --run-ref manual:2026-08-31:us-growth \
        --yes

There is deliberately no scheduler, backfill mode, or live scanner activation
in this script.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.infra.db.repositories.canslim_v2_shadow_repo import (
    SqlCANSLIMV2ShadowRepository,
)
from app.services.canslim_v2_prospective_shadow_service import (
    CANSLIMV2ProspectiveShadowCollector,
    SqlMarketExposureSnapshotReader,
)
from app.services.canslim_v2_shadow_batch_service import (
    CANSLIMV2ShadowBatchEvaluator,
)
from app.services.canslim_v2_shadow_service import CANSLIMV2ShadowEvaluator
from app.wiring.bootstrap import (
    build_runtime_services,
    reset_runtime_services,
    set_runtime_services,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "date must be YYYY-MM-DD"
        ) from exc


def _symbols(value: str) -> list[str]:
    symbols = [item.strip().upper() for item in value.split(",") if item.strip()]
    if not symbols:
        raise argparse.ArgumentTypeError("at least one symbol is required")
    if len(symbols) != len(set(symbols)):
        raise argparse.ArgumentTypeError("symbols must be unique")
    return symbols


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect exact-date prospective CAN SLIM V1-vs-V2 shadow evidence."
    )
    parser.add_argument(
        "--symbols",
        required=True,
        type=_symbols,
        help="Comma-separated symbols, e.g. AAPL,MSFT,NVDA",
    )
    parser.add_argument(
        "--as-of-date",
        required=True,
        type=_iso_date,
        help="Exact trading date expected in every stock and benchmark snapshot",
    )
    parser.add_argument(
        "--run-ref",
        required=True,
        help="Immutable research-run identity stored with every shadow row",
    )
    parser.add_argument(
        "--market",
        default="US",
        help="Single market for this prospective batch (default: US)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Commit shadow evidence. Without this flag the transaction is rolled back.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    db = SessionLocal()
    runtime = build_runtime_services(session_factory=SessionLocal)
    runtime_token = set_runtime_services(runtime)

    try:
        repository = SqlCANSLIMV2ShadowRepository(db)
        evaluator = CANSLIMV2ShadowEvaluator(repository)
        batch_evaluator = CANSLIMV2ShadowBatchEvaluator(evaluator)
        collector = CANSLIMV2ProspectiveShadowCollector(
            stock_data_provider=runtime.stock_data_provider(),
            market_rs_reader=runtime.market_rs_reader(),
            market_exposure_reader=SqlMarketExposureSnapshotReader(SessionLocal),
            batch_evaluator=batch_evaluator,
        )

        result = collector.collect(
            symbols=args.symbols,
            as_of_date=args.as_of_date,
            run_ref=args.run_ref,
            market=args.market,
        )

        batch = result.batch_result
        logger.info(
            "Prospective shadow run %s: market=%s date=%s symbols=%d created=%d reused=%d",
            result.run_ref,
            result.market,
            result.as_of_date.isoformat(),
            batch.requested,
            batch.created,
            batch.reused,
        )
        logger.info(
            "M snapshot: exposure=%.1f stance=%s",
            result.market_exposure_score,
            result.market_stance,
        )
        logger.info(
            "Market RS: formula=%s run_id=%d universe=%d",
            result.market_rs_formula_version,
            result.market_rs_run_id,
            result.market_rs_universe_size,
        )

        disagreements = [
            item.record.symbol
            for item in batch.results
            if item.record.action_disagreement
        ]
        if disagreements:
            logger.info("V1/V2 action disagreements: %s", ", ".join(disagreements))
        else:
            logger.info("V1/V2 action disagreements: none")

        if args.yes:
            db.commit()
            logger.info("COMMITTED: prospective shadow evidence is now persisted.")
        else:
            db.rollback()
            logger.info(
                "DRY RUN: rolled back all shadow evidence. Re-run with --yes to persist."
            )
        return 0
    except Exception:
        db.rollback()
        logger.exception("Prospective CAN SLIM shadow collection failed; rolled back.")
        return 1
    finally:
        db.close()
        reset_runtime_services(runtime_token)


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
