"""Export additive static shards for validated breadth contributors."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .breadth.contributor_query import (
    get_contributor_document,
    list_contributor_dates,
)


class StaticBreadthContributorExporter:
    def __init__(
        self,
        *,
        json_writer: Callable[[Path, Any], None] | None = None,
    ) -> None:
        self._json_writer = json_writer or self._write_json

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def export(
        self,
        db: Session,
        output_dir: Path,
        path_prefix: Path,
        breadth_payload: dict[str, Any],
    ) -> dict[str, str] | None:
        if not breadth_payload.get("available", False):
            return None
        market = str(breadth_payload.get("market") or "").strip().upper()
        if not market:
            current = (breadth_payload.get("payload") or {}).get("current") or {}
            market = str(current.get("market") or "").strip().upper()
        if not market:
            return None
        history = (breadth_payload.get("payload") or {}).get("history_90d") or []
        advertised_dates = {
            str(row.get("date"))
            for row in history
            if isinstance(row, dict) and row.get("date")
        }
        index = list_contributor_dates(db, market, limit=20)
        dates = tuple(
            calculation_date
            for calculation_date in index.dates
            if calculation_date.isoformat() in advertised_dates
        )
        if not dates:
            return None

        base_path = path_prefix / "breadth" / "contributors"
        for calculation_date in dates:
            document = get_contributor_document(db, market, calculation_date)
            self._json_writer(
                output_dir / base_path / f"{calculation_date.isoformat()}.json",
                {
                    "schema": document.schema,
                    "market": document.market,
                    "date": document.date.isoformat(),
                    "calculation_revision": document.calculation_revision,
                    "contributors": [
                        {
                            "symbol": item.symbol,
                            "company_name": item.company_name,
                            "ibd_industry_group": item.ibd_industry_group,
                            "daily_change_pct": item.daily_change_pct,
                            "signals": dict(item.signals),
                        }
                        for item in document.contributors
                    ],
                },
            )
        index_path = base_path / "index.json"
        self._json_writer(
            output_dir / index_path,
            {
                "schema": index.schema,
                "market": market,
                "calculation_revision": index.calculation_revision,
                "dates": [value.isoformat() for value in dates],
            },
        )
        return {"index_path": index_path.as_posix()}
