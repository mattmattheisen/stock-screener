"""Canonical breadth contributor contract tests."""

from __future__ import annotations

import importlib
from datetime import date
from types import MappingProxyType

import pandas as pd
import pytest

from app.services.breadth.engine import BreadthEngine, BreadthEngineRequest
from app.services.breadth.market_policy import get_breadth_market_policy
from app.services.breadth.types import BreadthUniverseMember, BreadthUniverseSnapshot
from app.services.point_in_time_universe_service import (
    hash_point_in_time_universe_symbols,
)


TARGET_DATE = date(2026, 8, 21)


def _contributors_module():
    try:
        return importlib.import_module("app.services.breadth.contributors")
    except ModuleNotFoundError as exc:
        pytest.fail(f"breadth contributor contract is missing: {exc}")


def test_contributor_registry_maps_exactly_the_supported_aggregate_fields():
    """Catches an omitted or accidentally interactive breadth count."""
    module = _contributors_module()

    assert {
        definition.aggregate_field
        for definition in module.BREADTH_CONTRIBUTOR_SIGNALS.values()
    } == {
        "stocks_up_4pct",
        "stocks_down_4pct",
        "stocks_up_25pct_quarter",
        "stocks_down_25pct_quarter",
        "stocks_up_25pct_month",
        "stocks_down_25pct_month",
        "stocks_up_50pct_month",
        "stocks_down_50pct_month",
        "stocks_up_13pct_34days",
        "stocks_down_13pct_34days",
        "atr_10x_extension_count",
    }


def _large_up_move_prices() -> pd.DataFrame:
    index = pd.bdate_range(end=TARGET_DATE, periods=252)
    close = pd.Series([10.0] * 251 + [16.0], index=index)
    volume = pd.Series([100_000.0] * 251 + [200_000.0], index=index)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.10,
            "Low": close - 0.10,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        },
        index=index,
    )


def _engine_request(*, include_large_move: bool) -> BreadthEngineRequest:
    types_module = importlib.import_module("app.services.breadth.types")
    metadata_type = getattr(types_module, "BreadthContributorMetadata", None)
    assert metadata_type is not None, "BreadthContributorMetadata is missing"
    snapshot = BreadthUniverseSnapshot(
        calculation_date=TARGET_DATE,
        members=(BreadthUniverseMember("AAA", "USD"),),
        broad_signature=hash_point_in_time_universe_symbols(("AAA",)),
    )
    prices = _large_up_move_prices()
    if not include_large_move:
        prices.loc[prices.index[-1], ["Open", "High", "Low", "Close", "Adj Close"]] = (
            10.0,
            10.1,
            9.9,
            10.0,
            10.0,
        )
    return BreadthEngineRequest(
        market="US",
        dates=(TARGET_DATE,),
        universes_by_date={TARGET_DATE: snapshot},
        prices_by_symbol={"AAA": prices},
        market_policy=get_breadth_market_policy("US"),
        contributor_metadata_by_date={
            TARGET_DATE: {
                "AAA": metadata_type(
                    company_name="Alpha Ltd",
                    ibd_industry_group="Semiconductors",
                )
            }
        },
    )


def test_engine_stores_one_symbol_once_with_all_qualifying_signals():
    """Catches duplicated stock identities or discarded per-signal values."""
    assert hasattr(BreadthEngine, "calculate_with_contributors")

    batch = BreadthEngine().calculate_with_contributors(
        _engine_request(include_large_move=True)
    )
    aggregate = batch.daily_results[TARGET_DATE]
    snapshot = batch.contributor_snapshots[TARGET_DATE]

    assert len(snapshot.contributors) == 1
    contributor = snapshot.contributors[0]
    assert contributor.symbol == "AAA"
    assert contributor.company_name == "Alpha Ltd"
    assert contributor.ibd_industry_group == "Semiconductors"
    assert contributor.daily_change_pct == pytest.approx(60.0)
    assert contributor.signals["up_4pct"] == pytest.approx(60.0)
    assert contributor.signals["up_25pct_month"] == pytest.approx(60.0)
    assert contributor.signals["up_50pct_month"] == pytest.approx(60.0)
    assert contributor.signals["up_25pct_quarter"] == pytest.approx(60.0)
    assert contributor.signals["up_13pct_34days"] == pytest.approx(60.0)
    assert contributor.signals["atr_10x_extension"] >= 10.0
    assert aggregate.values.stocks_up_4pct == 1
    assert aggregate.values.atr_10x_extension_count == 1


def test_engine_emits_a_complete_snapshot_when_no_stock_qualifies():
    """Catches treating a valid zero-contributor session as missing data."""
    assert hasattr(BreadthEngine, "calculate_with_contributors")

    batch = BreadthEngine().calculate_with_contributors(
        _engine_request(include_large_move=False)
    )
    snapshot = batch.contributor_snapshots[TARGET_DATE]

    assert snapshot.schema_id == "breadth-contributors-v1"
    assert snapshot.contributors == ()


def test_shared_parser_normalizes_and_reconciles_transport_rows():
    module = _contributors_module()
    contributors = module.parse_contributor_rows(
        [
            {
                "symbol": " AAA ",
                "company_name": "Alpha",
                "ibd_industry_group": "",
                "daily_change_pct": 5,
                "signals": {"up_4pct": 5},
            }
        ]
    )

    assert contributors[0].symbol == "AAA"
    assert contributors[0].ibd_industry_group == "No Group"
    assert contributors[0].signals == MappingProxyType({"up_4pct": 5.0})
    module.reconcile_contributor_aggregate(
        contributors,
        {
            definition.aggregate_field: int(signal_key == "up_4pct")
            for signal_key, definition in module.BREADTH_CONTRIBUTOR_SIGNALS.items()
        },
    )


@pytest.mark.parametrize(
    "row",
    [
        {"symbol": "", "signals": {"up_4pct": 5}},
        {"symbol": "AAA", "signals": {"unknown": 5}},
        {"symbol": "AAA", "signals": {"up_4pct": True}},
        {"symbol": "AAA", "signals": {}},
    ],
)
def test_shared_parser_rejects_invalid_transport_rows(row):
    module = _contributors_module()

    with pytest.raises(module.BreadthContributorContractError):
        module.parse_contributor_rows([row])
