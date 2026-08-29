"""Unit tests for canonical contributor group attribution."""

from __future__ import annotations

from datetime import date
from inspect import signature
from types import MappingProxyType

from app.services.breadth.contributor_query import (
    BreadthContributorDocumentPayload,
    BreadthContributorItemPayload,
)
from app.services.breadth_attribution_service import (
    NO_GROUP_LABEL,
    BreadthAttributionService,
)


def _item(
    symbol: str,
    *,
    group: str = "Software",
    daily_change_pct: float,
    signal: str,
) -> BreadthContributorItemPayload:
    return BreadthContributorItemPayload(
        symbol=symbol,
        company_name=f"{symbol} Co",
        ibd_industry_group=group,
        daily_change_pct=daily_change_pct,
        signals=MappingProxyType({signal: daily_change_pct}),
    )


def _document(
    calculation_date: date,
    *contributors: BreadthContributorItemPayload,
) -> BreadthContributorDocumentPayload:
    return BreadthContributorDocumentPayload(
        schema="breadth-contributors-v1",
        market="US",
        date=calculation_date,
        calculation_revision=3,
        contributors=contributors,
    )


def test_attribution_accepts_documents_instead_of_price_frames():
    parameters = signature(BreadthAttributionService.compute).parameters

    assert "documents" in parameters
    assert "price_data" not in parameters
    assert "symbols_meta" not in parameters


def test_compute_projects_frozen_groups_and_daily_changes():
    result = BreadthAttributionService().compute(
        documents=(
            _document(
                date(2026, 8, 21),
                _item("UP", daily_change_pct=6.0, signal="up_4pct"),
                _item(
                    "DOWN",
                    group="Banks",
                    daily_change_pct=-5.0,
                    signal="down_4pct",
                ),
                _item(
                    "MONTH",
                    group="Ignored",
                    daily_change_pct=1.0,
                    signal="up_25pct_month",
                ),
            ),
        )
    )

    assert result == [
        {
            "date": "2026-08-21",
            "stocks_up_4pct": 1,
            "stocks_down_4pct": 1,
            "groups": [
                {
                    "group": "Software",
                    "up_count": 1,
                    "down_count": 0,
                    "net": 1,
                    "up_stocks": [
                        {
                            "symbol": "UP",
                            "name": "UP Co",
                            "pct_change": 6.0,
                            "close": None,
                        }
                    ],
                    "down_stocks": [],
                },
                {
                    "group": "Banks",
                    "up_count": 0,
                    "down_count": 1,
                    "net": -1,
                    "up_stocks": [],
                    "down_stocks": [
                        {
                            "symbol": "DOWN",
                            "name": "DOWN Co",
                            "pct_change": -5.0,
                            "close": None,
                        }
                    ],
                },
            ],
        }
    ]


def test_compute_uses_no_group_and_returns_oldest_to_newest():
    newer = _document(
        date(2026, 8, 21),
        _item(
            "NEW",
            group="",
            daily_change_pct=7.0,
            signal="up_4pct",
        ),
    )
    older = _document(
        date(2026, 8, 20),
        _item(
            "OLD",
            group=NO_GROUP_LABEL,
            daily_change_pct=-7.0,
            signal="down_4pct",
        ),
    )

    result = BreadthAttributionService().compute(documents=(newer, older))

    assert [row["date"] for row in result] == ["2026-08-20", "2026-08-21"]
    assert result[0]["groups"][0]["group"] == NO_GROUP_LABEL
    assert result[1]["groups"][0]["group"] == NO_GROUP_LABEL
