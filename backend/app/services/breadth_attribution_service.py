"""Project canonical breadth contributor documents into legacy group history."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.breadth.contributor_query import BreadthContributorDocumentPayload
from app.services.breadth.contributors import NO_GROUP_LABEL


class BreadthAttributionService:
    """Summarize frozen ±4% contributor snapshots by IBD industry group."""

    def compute(
        self,
        *,
        documents: Iterable[BreadthContributorDocumentPayload],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for document in sorted(documents, key=lambda item: item.date):
            groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
            for contributor in document.contributors:
                direction = (
                    "up"
                    if "up_4pct" in contributor.signals
                    else "down"
                    if "down_4pct" in contributor.signals
                    else None
                )
                if direction is None:
                    continue
                group = self._resolve_group(contributor.ibd_industry_group)
                bucket = groups.setdefault(
                    group,
                    {"up_stocks": [], "down_stocks": []},
                )
                bucket[f"{direction}_stocks"].append(
                    {
                        "symbol": contributor.symbol,
                        "name": contributor.company_name,
                        "pct_change": contributor.daily_change_pct,
                        "close": None,
                    }
                )

            groups_payload: list[dict[str, Any]] = []
            for group_name, bucket in groups.items():
                up_stocks = sorted(
                    bucket["up_stocks"],
                    key=lambda row: (
                        -(row["pct_change"] or 0.0),
                        row["symbol"],
                    ),
                )
                down_stocks = sorted(
                    bucket["down_stocks"],
                    key=lambda row: (
                        row["pct_change"] or 0.0,
                        row["symbol"],
                    ),
                )
                up_count = len(up_stocks)
                down_count = len(down_stocks)
                groups_payload.append(
                    {
                        "group": group_name,
                        "up_count": up_count,
                        "down_count": down_count,
                        "net": up_count - down_count,
                        "up_stocks": up_stocks,
                        "down_stocks": down_stocks,
                    }
                )
            groups_payload.sort(
                key=lambda row: (
                    -(row["up_count"] + row["down_count"]),
                    -row["net"],
                    row["group"],
                )
            )
            results.append(
                {
                    "date": document.date.isoformat(),
                    "stocks_up_4pct": sum(row["up_count"] for row in groups_payload),
                    "stocks_down_4pct": sum(
                        row["down_count"] for row in groups_payload
                    ),
                    "groups": groups_payload,
                }
            )
        return results

    @staticmethod
    def _resolve_group(raw_group: Any) -> str:
        text = str(raw_group or "").strip()
        return text or NO_GROUP_LABEL


__all__ = ["NO_GROUP_LABEL", "BreadthAttributionService"]
