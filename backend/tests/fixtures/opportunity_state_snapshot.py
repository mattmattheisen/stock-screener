"""Deterministic cross-surface opportunity-state snapshot.

The fixture enters through the pure policy, persists the resulting projection,
then exposes the real feature-store and static-export boundaries used by tests.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.contracts.filter_expression import expression_from_payload
from app.database import Base
from app.domain.common.query import SortOrder, SortSpec
from app.domain.scanning.filter_expression_evaluator import evaluate_expression
from app.domain.scanning.filter_expression_model import FilterExpression
from app.domain.scanning.legacy_filter_expression import legacy_filters_to_expression
from app.domain.scanning.opportunity_state import (
    InvalidationEvidence,
    OpportunityInputs,
    evaluate_opportunity_state,
)
from app.infra.db.models.feature_store import FeatureRun, StockFeatureDaily
from app.infra.db.repositories.feature_store_repo import SqlFeatureStoreRepository
from app.models.stock import StockFundamental
from app.models.stock_universe import StockUniverse
from app.schemas.scanning import ScanResultItem
from app.services.preset_screens import PRESET_SCREENS
from app.services.static_site_export_service import StaticSiteExportService


AS_OF_DATE = date(2026, 8, 21)
RUN_ID = 1201


def _complete_inputs(**changes) -> OpportunityInputs:
    values = {
        "market": "US",
        "mic": "XNAS",
        "as_of_date": AS_OF_DATE,
        "benchmark_symbol": "SPY",
        "benchmark_as_of_date": AS_OF_DATE,
        "benchmark_relative_return_65d": 0.08,
        "rs_rating_1m": 90.0,
        "rs_rating_3m": 80.0,
        "rs_line_new_high": True,
        "rs_line_blue_dot": False,
        "stage": 2,
        "ma_alignment": True,
        "invalidation_evidence_available": True,
        "invalidation_flags": (),
        "setup_payload_available": True,
        "pattern_primary": "vcp",
        "squeeze": True,
        "tight_closes_count": 3,
        "quiet_days_count": 3,
        "volume_vs_50d": 0.70,
        "volume_dry_up_max": 0.80,
        "liquidity_available": True,
        "liquidity_passes": True,
        "feature_status": "complete",
        "is_scannable": True,
        "event_calendar_available": True,
        "earnings_soon": False,
        "setup_ready": True,
        "in_early_zone": True,
        "extended": False,
        "prior_run_required": False,
        "prior_run_available": False,
        "deterioration_confirmed": False,
        "stewardship_status": None,
    }
    values.update(changes)
    return OpportunityInputs(**values)


def _opportunity_inputs_by_symbol() -> dict[str, OpportunityInputs]:
    return {
        "EXIT": _complete_inputs(
            invalidation_flags=(
                InvalidationEvidence("breaks_50d_support", True),
            ),
        ),
        "DETERIORATING": _complete_inputs(
            rs_rating_1m=80.0,
            rs_rating_3m=70.0,
            prior_run_required=True,
            prior_run_available=True,
            deterioration_confirmed=True,
        ),
        "EVENT": _complete_inputs(
            benchmark_as_of_date=date(2026, 8, 20),
            rs_rating_1m=88.0,
            rs_rating_3m=78.0,
            earnings_soon=True,
        ),
        "EXTENDED": _complete_inputs(
            rs_rating_1m=80.0,
            rs_rating_3m=70.0,
            extended=True,
        ),
        "LIMITED": _complete_inputs(event_calendar_available=False),
        "READY": _complete_inputs(),
        "WATCH": _complete_inputs(
            rs_rating_1m=80.0,
            rs_rating_3m=70.0,
            setup_ready=False,
        ),
    }


def _scan_payload(row) -> dict:
    return ScanResultItem.from_domain(
        row,
        include_setup_payload=False,
    ).model_dump(
        mode="json",
        exclude={"se_explain", "se_candidates"},
    )


def _correction_survivors_screen(screens):
    return next(screen for screen in screens if screen["id"] == "correction_survivors")


class OpportunityStateParitySnapshot:
    def __init__(self, engine, session_factory) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._static_exporter = StaticSiteExportService(
            session_factory,
            price_cache=object(),
            fundamentals_cache=object(),
            benchmark_cache=object(),
        )

    def close(self) -> None:
        self._engine.dispose()

    def query_live_rows(self) -> list[dict]:
        with self._session_factory() as db:
            rows = SqlFeatureStoreRepository(db).query_all_as_scan_results(
                RUN_ID,
                FilterExpression(),
                SortSpec(field="symbol", order=SortOrder.ASC),
                include_sparklines=False,
                include_setup_payload=False,
            )
            return [_scan_payload(row) for row in rows]

    def query_live_survivor_symbols(self) -> list[str]:
        screen = _correction_survivors_screen(PRESET_SCREENS)
        with self._session_factory() as db:
            rows = SqlFeatureStoreRepository(db).query_all_as_scan_results(
                RUN_ID,
                legacy_filters_to_expression(screen["filters"]),
                SortSpec(
                    field=screen["sort_by"],
                    order=SortOrder(screen["sort_order"]),
                ),
                include_sparklines=False,
                include_setup_payload=False,
            )
            return [str(row.symbol) for row in rows]

    def export_and_read_static_rows(self, output_dir: Path) -> list[dict]:
        output_dir = Path(output_dir)
        with self._session_factory() as db:
            run = db.get(FeatureRun, RUN_ID)
            self._static_exporter._export_scan_bundle(  # noqa: SLF001
                db=db,
                output_dir=output_dir,
                generated_at="2026-08-21T22:00:00Z",
                run=run,
                market="US",
            )

        manifest = self.read_static_manifest(output_dir)
        rows: list[dict] = []
        for chunk in manifest["chunks"]:
            payload = json.loads(
                (output_dir / chunk["path"]).read_text(encoding="utf-8")
            )
            rows.extend(payload["rows"])
        return rows

    @staticmethod
    def read_static_manifest(output_dir: Path) -> dict:
        return json.loads(
            (Path(output_dir) / "scan" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )

    @staticmethod
    def static_survivor_symbols(rows: list[dict], manifest: dict) -> list[str]:
        screen = _correction_survivors_screen(manifest["preset_screens"])
        expression = expression_from_payload(screen["filter_expression"])
        matching = [row for row in rows if evaluate_expression(row, expression)]

        def sort_key(row):
            value = row.get(screen["sort_by"])
            return (
                value is None,
                -float(value) if value is not None else 0.0,
                str(row.get("symbol") or ""),
            )

        return [row["symbol"] for row in sorted(matching, key=sort_key)]


def build_parity_snapshot(database_path: Path) -> OpportunityStateParitySnapshot:
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(
        engine,
        tables=[
            FeatureRun.__table__,
            StockFeatureDaily.__table__,
            StockUniverse.__table__,
            StockFundamental.__table__,
        ],
    )
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    opportunity_inputs = _opportunity_inputs_by_symbol()
    with session_factory() as db:
        db.add(
            FeatureRun(
                id=RUN_ID,
                as_of_date=AS_OF_DATE,
                run_type="daily_snapshot",
                status="published",
                config_json={"market": "US"},
                published_at=datetime(2026, 8, 21, 22, 0, 0),
            )
        )
        for index, (symbol, inputs) in enumerate(opportunity_inputs.items()):
            projection = evaluate_opportunity_state(inputs).projection()
            db.add(
                StockUniverse(
                    symbol=symbol,
                    name=f"{symbol.title()} Fixture",
                    market="US",
                    exchange="NASDAQ",
                    currency="USD",
                )
            )
            db.add(
                StockFeatureDaily(
                    run_id=RUN_ID,
                    symbol=symbol,
                    as_of_date=AS_OF_DATE,
                    composite_score=90.0 - index,
                    overall_rating=5,
                    passes_count=2,
                    details_json={
                        "rating": "Strong Buy",
                        "current_price": 100.0 + index,
                        "avg_dollar_volume": 150_000_000.0 + index,
                        "screeners_run": ["minervini", "setup_engine"],
                        **projection,
                        "setup_engine": {
                            "explain": {"summary": "must stay out of static rows"},
                            "candidates": [{"pattern": "vcp"}],
                        },
                    },
                )
            )

        db.add(
            StockUniverse(
                symbol="LEGACY",
                name="Legacy Fixture",
                market="US",
                exchange="NASDAQ",
                currency="USD",
            )
        )
        db.add(
            StockFeatureDaily(
                run_id=RUN_ID,
                symbol="LEGACY",
                as_of_date=AS_OF_DATE,
                composite_score=50.0,
                overall_rating=3,
                passes_count=0,
                details_json={
                    "rating": "Watch",
                    "current_price": 50.0,
                    "avg_dollar_volume": 150_000_100.0,
                    "screeners_run": ["minervini"],
                },
            )
        )
        db.commit()

    return OpportunityStateParitySnapshot(engine, session_factory)


__all__ = ["OpportunityStateParitySnapshot", "build_parity_snapshot"]
