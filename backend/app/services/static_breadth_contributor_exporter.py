"""Export additive static shards for validated breadth contributors."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from .breadth.contributor_query import (
    BreadthContributorSnapshotInconsistent,
    BreadthContributorSnapshotUnavailable,
    get_contributor_document,
    list_contributor_dates,
)
from .breadth.contributors import (
    BreadthContributorContractError,
    contributor_calculation_signature,
    parse_contributor_rows,
    reconcile_contributor_aggregate,
)


class StaticBreadthContributorUnavailable(RuntimeError):
    """Validated contributor data disappeared or changed during export."""


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
        expected_calculation_signatures: dict[str, str] | None = None,
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
        aggregates_by_date = {
            str(row.get("date")): row
            for row in history
            if isinstance(row, dict) and row.get("date")
        }
        index = list_contributor_dates(db, market, limit=20)
        dates = tuple(
            calculation_date
            for calculation_date in index.dates
            if calculation_date.isoformat() in aggregates_by_date
        )
        if not dates:
            destination = output_dir / path_prefix / "breadth" / "contributors"
            if destination.exists():
                shutil.rmtree(destination)
            return None

        base_path = path_prefix / "breadth" / "contributors"
        destination = output_dir / base_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=".contributors-",
                dir=destination.parent,
            )
        )
        try:
            for calculation_date in dates:
                try:
                    document = get_contributor_document(
                        db,
                        market,
                        calculation_date,
                    )
                except (
                    BreadthContributorSnapshotInconsistent,
                    BreadthContributorSnapshotUnavailable,
                ) as exc:
                    raise StaticBreadthContributorUnavailable(str(exc)) from exc
                self._json_writer(
                    staging / f"{calculation_date.isoformat()}.json",
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
            self._json_writer(
                staging / "index.json",
                {
                    "schema": index.schema,
                    "market": market,
                    "calculation_revision": index.calculation_revision,
                    "dates": [value.isoformat() for value in dates],
                },
            )
            self._validate_stage(
                staging,
                market=market,
                dates=dates,
                aggregates_by_date=aggregates_by_date,
                expected_calculation_signatures=expected_calculation_signatures,
            )
            self._replace_directory(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        index_path = base_path / "index.json"
        return {"index_path": index_path.as_posix()}

    @staticmethod
    def _validate_stage(
        staging: Path,
        *,
        market: str,
        dates: tuple,
        aggregates_by_date: dict[str, dict[str, Any]],
        expected_calculation_signatures: dict[str, str] | None,
    ) -> None:
        expected_names = {"index.json"} | {
            f"{value.isoformat()}.json" for value in dates
        }
        if {path.name for path in staging.iterdir()} != expected_names:
            raise ValueError("Contributor staging files do not match advertised dates")
        index = json.loads((staging / "index.json").read_text(encoding="utf-8"))
        if index.get("market") != market or index.get("dates") != [
            value.isoformat() for value in dates
        ]:
            raise ValueError("Contributor staging index identity is invalid")
        for calculation_date in dates:
            document = json.loads(
                (staging / f"{calculation_date.isoformat()}.json").read_text(
                    encoding="utf-8"
                )
            )
            if (
                document.get("market") != market
                or document.get("date") != calculation_date.isoformat()
            ):
                raise ValueError("Contributor staging document identity is invalid")
            try:
                contributors = parse_contributor_rows(
                    document.get("contributors") or ()
                )
                expected_signature = None
                if expected_calculation_signatures is not None:
                    expected_signature = expected_calculation_signatures.get(
                        calculation_date.isoformat()
                    )
                    if expected_signature is None:
                        raise BreadthContributorContractError(
                            "Static breadth engine did not provide a contributor "
                            "calculation signature"
                        )
                    actual_signature = contributor_calculation_signature(contributors)
                    if actual_signature != expected_signature:
                        raise BreadthContributorContractError(
                            "Contributor calculation signature does not match "
                            "the static breadth engine"
                        )
                reconcile_contributor_aggregate(
                    contributors,
                    aggregates_by_date[calculation_date.isoformat()],
                )
            except (
                BreadthContributorContractError,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                raise StaticBreadthContributorUnavailable(
                    f"Contributor shard disagrees with static breadth for "
                    f"{market}/{calculation_date}: {exc}"
                ) from exc

    @staticmethod
    def _replace_directory(staging: Path, destination: Path) -> None:
        backup = destination.parent / f".contributors-backup-{uuid4().hex}"
        moved_existing = False
        try:
            if destination.exists():
                destination.replace(backup)
                moved_existing = True
            staging.replace(destination)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            if moved_existing and backup.exists():
                backup.replace(destination)
            raise
        else:
            if backup.exists():
                shutil.rmtree(backup)
