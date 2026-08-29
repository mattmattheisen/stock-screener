from __future__ import annotations

import json
import math
from pathlib import Path

from app.services.breadth.contributors import (
    BREADTH_CONTRIBUTOR_SIGNALS,
    CONTRIBUTOR_SCHEMA_ID,
)
from app.services.breadth.types import CURRENT_BREADTH_CALCULATION_REVISION


class StaticBreadthContributorAssetError(RuntimeError):
    """A static breadth contributor asset is incomplete or inconsistent."""


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
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if (
        index.get("schema") != CONTRIBUTOR_SCHEMA_ID
        or index.get("market") != market
        or index.get("calculation_revision")
        != CURRENT_BREADTH_CALCULATION_REVISION
    ):
        raise StaticBreadthContributorAssetError("index identity is invalid")
    dates = index.get("dates")
    if (
        not isinstance(dates, list)
        or not dates
        or len(dates) > 20
        or len(set(dates)) != len(dates)
        or dates != sorted(dates, reverse=True)
    ):
        raise StaticBreadthContributorAssetError("index dates are invalid")

    breadth_path = market_dir / "breadth.json"
    if not breadth_path.is_file():
        raise StaticBreadthContributorAssetError("breadth.json is absent")
    breadth = json.loads(breadth_path.read_text(encoding="utf-8"))
    rows = (breadth.get("payload") or {}).get("history_90d") or []
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
        document = json.loads(document_path.read_text(encoding="utf-8"))
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
        counts = {key: 0 for key in BREADTH_CONTRIBUTOR_SIGNALS}
        symbols: set[str] = set()
        for contributor in contributors:
            if not isinstance(contributor, dict):
                raise StaticBreadthContributorAssetError(
                    f"contributor row is invalid for {date_value}"
                )
            symbol = str(contributor.get("symbol") or "").strip()
            if not symbol or symbol in symbols:
                raise StaticBreadthContributorAssetError(
                    f"contributor symbols are invalid for {date_value}"
                )
            symbols.add(symbol)
            daily_change = contributor.get("daily_change_pct")
            if daily_change is not None and (
                isinstance(daily_change, bool)
                or not math.isfinite(float(daily_change))
            ):
                raise StaticBreadthContributorAssetError(
                    f"daily change is invalid for {symbol}/{date_value}"
                )
            signals = contributor.get("signals")
            if not isinstance(signals, dict) or not signals:
                raise StaticBreadthContributorAssetError(
                    f"signals are invalid for {symbol}/{date_value}"
                )
            for signal_key, value in signals.items():
                if (
                    signal_key not in counts
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                ):
                    raise StaticBreadthContributorAssetError(
                        f"signal is invalid for {symbol}/{date_value}"
                    )
                counts[signal_key] += 1
        aggregate = aggregates_by_date.get(date_value)
        if aggregate is None:
            raise StaticBreadthContributorAssetError(
                f"aggregate breadth row is absent for {date_value}"
            )
        for signal_key, definition in BREADTH_CONTRIBUTOR_SIGNALS.items():
            if counts[signal_key] != aggregate.get(definition.aggregate_field):
                raise StaticBreadthContributorAssetError(
                    f"count mismatch for {definition.aggregate_field}/{date_value}"
                )
