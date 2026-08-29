from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.services.breadth.contributors import (
    BREADTH_CONTRIBUTOR_SIGNALS,
    CONTRIBUTOR_SCHEMA_ID,
    BreadthContributorContractError,
    parse_contributor_rows,
    reconcile_contributor_aggregate,
)
from app.services.breadth.types import CURRENT_BREADTH_CALCULATION_REVISION


class StaticBreadthContributorAssetError(RuntimeError):
    """A static breadth contributor asset is incomplete or inconsistent."""


def _load_json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StaticBreadthContributorAssetError(
            f"{label} is not readable JSON"
        ) from exc
    if not isinstance(value, dict):
        raise StaticBreadthContributorAssetError(f"{label} is not an object")
    return value


def validate_static_breadth_contributor_asset(
    *,
    market: str,
    market_dir: Path,
    descriptor: object,
) -> None:
    if not isinstance(descriptor, dict):
        raise StaticBreadthContributorAssetError("descriptor is not an object")
    advertised_path = str(descriptor.get("index_path") or "").strip()
    if not advertised_path:
        raise StaticBreadthContributorAssetError("index_path is missing")
    relative = Path(advertised_path)
    published_prefix = Path("markets") / market.lower()
    try:
        relative = relative.relative_to(published_prefix)
    except ValueError:
        pass
    artifact_root = market_dir.resolve()
    index_path = (artifact_root / relative).resolve()
    try:
        index_path.relative_to(artifact_root)
    except ValueError as exc:
        raise StaticBreadthContributorAssetError(
            "index_path escapes its artifact"
        ) from exc
    if not index_path.is_file():
        raise StaticBreadthContributorAssetError("advertised index file is absent")
    index = _load_json_object(index_path, "contributor index")
    if (
        index.get("schema") != CONTRIBUTOR_SCHEMA_ID
        or index.get("market") != market
        or index.get("calculation_revision") != CURRENT_BREADTH_CALCULATION_REVISION
    ):
        raise StaticBreadthContributorAssetError("index identity is invalid")
    dates = index.get("dates")
    if (
        not isinstance(dates, list)
        or not dates
        or not all(isinstance(value, str) for value in dates)
        or len(dates) > 20
        or len(set(dates)) != len(dates)
    ):
        raise StaticBreadthContributorAssetError("index dates are invalid")
    try:
        parsed_dates = [date.fromisoformat(value) for value in dates]
    except ValueError as exc:
        raise StaticBreadthContributorAssetError("index dates are invalid") from exc
    if parsed_dates != sorted(parsed_dates, reverse=True):
        raise StaticBreadthContributorAssetError("index dates are invalid")

    breadth_path = market_dir / "breadth.json"
    if not breadth_path.is_file():
        raise StaticBreadthContributorAssetError("breadth.json is absent")
    breadth = _load_json_object(breadth_path, "breadth.json")
    payload = breadth.get("payload")
    if not isinstance(payload, dict):
        raise StaticBreadthContributorAssetError(
            "breadth.json payload is not an object"
        )
    rows = payload.get("history_90d")
    if not isinstance(rows, list):
        raise StaticBreadthContributorAssetError(
            "breadth.json history_90d is not a list"
        )
    aggregates_by_date = {
        str(row.get("date")): row
        for row in rows
        if isinstance(row, dict) and row.get("date")
    }
    for date_value in dates:
        document_path = index_path.parent / f"{date_value}.json"
        if not document_path.is_file():
            raise StaticBreadthContributorAssetError(
                f"contributor document is absent for {date_value}"
            )
        document = _load_json_object(
            document_path,
            f"contributor document for {date_value}",
        )
        if (
            document.get("schema") != CONTRIBUTOR_SCHEMA_ID
            or document.get("market") != market
            or document.get("date") != date_value
            or document.get("calculation_revision")
            != CURRENT_BREADTH_CALCULATION_REVISION
        ):
            raise StaticBreadthContributorAssetError(
                f"contributor document identity is invalid for {date_value}"
            )
        contributors = document.get("contributors")
        if not isinstance(contributors, list):
            raise StaticBreadthContributorAssetError(
                f"contributors are invalid for {date_value}"
            )
        aggregate = aggregates_by_date.get(date_value)
        if aggregate is None:
            raise StaticBreadthContributorAssetError(
                f"aggregate breadth row is absent for {date_value}"
            )
        try:
            parsed = parse_contributor_rows(contributors)
            reconcile_contributor_aggregate(
                parsed,
                {
                    definition.aggregate_field: aggregate.get(
                        definition.aggregate_field
                    )
                    for definition in BREADTH_CONTRIBUTOR_SIGNALS.values()
                },
            )
        except (BreadthContributorContractError, TypeError, ValueError) as exc:
            raise StaticBreadthContributorAssetError(
                f"invalid contributors for {date_value}: {exc}"
            ) from exc
