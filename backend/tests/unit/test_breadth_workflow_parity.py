import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from app.database import Base
from app.models.breadth_contributor import (
    MarketBreadthContributor,
    MarketBreadthContributorSnapshot,
)
from app.models.market_breadth import MarketBreadth
from app.services.breadth.contributor_query import (
    BreadthContributorDocumentPayload,
    BreadthContributorItemPayload,
    get_contributor_document,
)
from app.services.breadth.engine import BreadthEngine, BreadthEngineRequest
from app.services.breadth.market_policy import get_breadth_market_policy
from app.services.breadth.persistence import BreadthPersistence
from app.services.breadth.types import (
    BreadthContributorMetadata,
    BreadthUniverseMember,
    BreadthUniverseSnapshot,
)
from app.services.breadth_attribution_service import BreadthAttributionService
from app.services.point_in_time_universe_service import (
    hash_point_in_time_universe_symbols,
)
from app.services.static_breadth_section_builder import StaticBreadthSectionBuilder
from app.services.static_breadth_contributor_exporter import (
    StaticBreadthContributorExporter,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _prices(final_close: float) -> pd.DataFrame:
    index = pd.bdate_range(end="2026-08-21", periods=70)
    close = pd.Series([100.0] * 69 + [final_close], index=index)
    volume = pd.Series([100_000.0] * 69 + [200_000.0], index=index)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        },
        index=index,
    )


def test_static_and_attribution_daily_counts_match_canonical_engine():
    calculation_date = date(2026, 8, 21)
    prices = {"UP": _prices(105.0), "DOWN": _prices(95.0)}
    members = (
        BreadthUniverseMember("DOWN", "USD"),
        BreadthUniverseMember("UP", "USD"),
    )
    snapshot = BreadthUniverseSnapshot(
        calculation_date=calculation_date,
        members=members,
        broad_signature=hash_point_in_time_universe_symbols(("DOWN", "UP")),
    )
    batch = BreadthEngine().calculate_with_contributors(
        BreadthEngineRequest(
            market="US",
            dates=(calculation_date,),
            universes_by_date={calculation_date: snapshot},
            prices_by_symbol=prices,
            market_policy=get_breadth_market_policy("US"),
            contributor_metadata_by_date={
                calculation_date: {
                    "UP": BreadthContributorMetadata("Up Co", "Group A"),
                    "DOWN": BreadthContributorMetadata("Down Co", "No Group"),
                }
            },
        )
    )
    canonical = batch.daily_results[calculation_date]
    snapshot = batch.contributor_snapshots[calculation_date]

    builder = StaticBreadthSectionBuilder(
        ui_snapshot_service=Mock(),
        price_cache=Mock(),
        benchmark_cache=Mock(),
    )
    static = builder._compute_breadth_metrics_by_date(
        [calculation_date],
        prices,
        market="US",
    )[calculation_date]
    attribution = BreadthAttributionService().compute(
        documents=(
            BreadthContributorDocumentPayload(
                schema=snapshot.schema_id,
                market=snapshot.market,
                date=snapshot.calculation_date,
                calculation_revision=snapshot.calculation_revision,
                contributors=tuple(
                    BreadthContributorItemPayload(
                        symbol=item.symbol,
                        company_name=item.company_name,
                        ibd_industry_group=item.ibd_industry_group,
                        daily_change_pct=item.daily_change_pct,
                        signals=item.signals,
                    )
                    for item in snapshot.contributors
                ),
            ),
        ),
    )[0]

    expected = (
        canonical.values.stocks_up_4pct,
        canonical.values.stocks_down_4pct,
    )
    assert (static["stocks_up_4pct"], static["stocks_down_4pct"]) == expected
    assert (
        attribution["stocks_up_4pct"],
        attribution["stocks_down_4pct"],
    ) == expected
    assert sum(group["up_count"] for group in attribution["groups"]) == expected[0]
    assert sum(group["down_count"] for group in attribution["groups"]) == expected[1]


@pytest.mark.parametrize("market", ["US", "CA"])
def test_live_and_static_contributor_documents_match(market: str, tmp_path: Path):
    calculation_date = date(2026, 8, 21)
    currency = get_breadth_market_policy(market).currency
    prices = {"UP": _prices(200.0), "DOWN": _prices(40.0)}
    members = tuple(
        BreadthUniverseMember(symbol, currency) for symbol in sorted(prices)
    )
    universe = BreadthUniverseSnapshot(
        calculation_date=calculation_date,
        members=members,
        broad_signature=hash_point_in_time_universe_symbols(prices),
    )
    batch = BreadthEngine().calculate_with_contributors(
        BreadthEngineRequest(
            market=market,
            dates=(calculation_date,),
            universes_by_date={calculation_date: universe},
            prices_by_symbol=prices,
            market_policy=get_breadth_market_policy(market),
            contributor_metadata_by_date={
                calculation_date: {
                    "UP": BreadthContributorMetadata("Up Co", "Software"),
                    "DOWN": BreadthContributorMetadata("Down Co", "No Group"),
                }
            },
        )
    )
    aggregate = batch.daily_results[calculation_date]
    snapshot = batch.contributor_snapshots[calculation_date]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            MarketBreadth.__table__,
            MarketBreadthContributorSnapshot.__table__,
            MarketBreadthContributor.__table__,
        ],
    )
    db = sessionmaker(bind=engine)()
    BreadthPersistence(db).upsert_daily(
        aggregate,
        contributor_snapshot=snapshot,
        duration_seconds=0.1,
    )

    live = get_contributor_document(db, market, calculation_date)
    asset = StaticBreadthContributorExporter().export(
        db,
        tmp_path,
        Path(f"markets/{market.lower()}"),
        {
            "available": True,
            "market": market,
            "payload": {
                "history_90d": [
                    {
                        **aggregate.to_record_mapping(),
                        "date": calculation_date.isoformat(),
                    }
                ]
            },
        },
    )
    assert asset is not None
    static = json.loads(
        (
            tmp_path
            / f"markets/{market.lower()}/breadth/contributors"
            / f"{calculation_date.isoformat()}.json"
        ).read_text(encoding="utf-8")
    )
    live_payload = {
        "schema": live.schema,
        "market": live.market,
        "date": live.date.isoformat(),
        "calculation_revision": live.calculation_revision,
        "contributors": [
            {
                "symbol": item.symbol,
                "company_name": item.company_name,
                "ibd_industry_group": item.ibd_industry_group,
                "daily_change_pct": item.daily_change_pct,
                "signals": dict(item.signals),
            }
            for item in live.contributors
        ],
    }
    assert static == live_payload
    signal_keys = {key for item in live.contributors for key in item.signals}
    assert {"up_4pct", "down_25pct_month", "atr_10x_extension"} <= signal_keys
