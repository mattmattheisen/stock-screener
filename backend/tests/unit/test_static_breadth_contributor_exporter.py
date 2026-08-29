from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from app.database import Base
from app.models.breadth_contributor import (
    MarketBreadthContributor,
    MarketBreadthContributorSnapshot,
)
from app.models.market_breadth import MarketBreadth
from app.services.static_breadth_contributor_exporter import (
    StaticBreadthContributorExporter,
)
from app.services.static_artifact_combiner import StaticArtifactCombiner
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            MarketBreadth.__table__,
            MarketBreadthContributorSnapshot.__table__,
            MarketBreadthContributor.__table__,
        ],
    )
    return sessionmaker(bind=engine)()


def _seed(db, market: str, calculation_date: date):
    db.add(
        MarketBreadth(
            market=market,
            date=calculation_date,
            calculation_revision=3,
            stocks_up_4pct=1,
            stocks_down_4pct=0,
            stocks_up_25pct_quarter=0,
            stocks_down_25pct_quarter=0,
            stocks_up_25pct_month=0,
            stocks_down_25pct_month=0,
            stocks_up_50pct_month=0,
            stocks_down_50pct_month=0,
            stocks_up_13pct_34days=0,
            stocks_down_13pct_34days=0,
            atr_10x_extension_count=0,
            total_stocks_scanned=1,
        )
    )
    db.add(
        MarketBreadthContributorSnapshot(
            market=market,
            date=calculation_date,
            calculation_revision=3,
            schema_id="breadth-contributors-v1",
            contributors=[
                MarketBreadthContributor(
                    symbol="AAA",
                    company_name="Alpha",
                    ibd_industry_group="Semiconductors",
                    daily_change_pct=5.0,
                    signals_json={"up_4pct": 5.0},
                )
            ],
        )
    )
    db.commit()


def _breadth_payload(market: str, dates: list[date]):
    return {
        "available": True,
        "market": market,
        "payload": {
            "history_90d": [
                {
                    "market": market,
                    "date": item.isoformat(),
                    "stocks_up_4pct": 1,
                    "stocks_down_4pct": 0,
                    "stocks_up_25pct_quarter": 0,
                    "stocks_down_25pct_quarter": 0,
                    "stocks_up_25pct_month": 0,
                    "stocks_down_25pct_month": 0,
                    "stocks_up_50pct_month": 0,
                    "stocks_down_50pct_month": 0,
                    "stocks_up_13pct_34days": 0,
                    "stocks_down_13pct_34days": 0,
                    "atr_10x_extension_count": 0,
                }
                for item in reversed(dates)
            ]
        },
    }


def test_export_writes_index_and_twenty_date_shards(tmp_path: Path):
    db = _db_session()
    first = date(2026, 8, 1)
    dates = [first + timedelta(days=offset) for offset in range(20)]
    for calculation_date in dates:
        _seed(db, "CA", calculation_date)

    asset = StaticBreadthContributorExporter().export(
        db,
        tmp_path,
        Path("markets/ca"),
        _breadth_payload("CA", dates),
    )

    assert asset == {"index_path": "markets/ca/breadth/contributors/index.json"}
    index = json.loads((tmp_path / asset["index_path"]).read_text())
    assert index["schema"] == "breadth-contributors-v1"
    assert index["market"] == "CA"
    assert len(index["dates"]) == 20
    assert index["dates"] == sorted(index["dates"], reverse=True)
    document = json.loads(
        (
            tmp_path / "markets/ca/breadth/contributors" / f"{index['dates'][0]}.json"
        ).read_text()
    )
    assert document["market"] == "CA"
    assert document["contributors"][0]["symbol"] == "AAA"
    (tmp_path / "markets/ca/breadth.json").write_text(
        json.dumps(_breadth_payload("CA", dates)),
        encoding="utf-8",
    )
    StaticArtifactCombiner._validate_breadth_contributor_asset(
        market="CA",
        market_dir=tmp_path / "markets/ca",
        descriptor=asset,
    )


def test_export_is_additive_and_omits_asset_when_no_snapshot(tmp_path: Path):
    db = _db_session()
    payload = _breadth_payload("DE", [date(2026, 8, 28)])

    assert (
        StaticBreadthContributorExporter().export(
            db,
            tmp_path,
            Path("markets/de"),
            payload,
        )
        is None
    )
    assert payload["available"] is True


def test_export_preserves_previous_directory_when_a_stage_write_fails(
    tmp_path: Path,
):
    db = _db_session()
    calculation_date = date(2026, 8, 28)
    _seed(db, "DE", calculation_date)
    destination = tmp_path / "markets/de/breadth/contributors"
    destination.mkdir(parents=True)
    (destination / "index.json").write_text('{"previous": true}', encoding="utf-8")
    (destination / "stale.json").write_text('{"stale": true}', encoding="utf-8")
    writes = 0

    def failing_writer(path, payload):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("disk full")
        StaticBreadthContributorExporter._write_json(path, payload)

    with pytest.raises(OSError, match="disk full"):
        StaticBreadthContributorExporter(json_writer=failing_writer).export(
            db,
            tmp_path,
            Path("markets/de"),
            _breadth_payload("DE", [calculation_date]),
        )

    assert json.loads((destination / "index.json").read_text()) == {"previous": True}
    assert (destination / "stale.json").is_file()
    assert not (destination / f"{calculation_date.isoformat()}.json").exists()
    assert not any(
        path.name.startswith(".contributors-") for path in destination.parent.iterdir()
    )


def test_successful_export_replaces_directory_and_removes_stale_shards(
    tmp_path: Path,
):
    db = _db_session()
    calculation_date = date(2026, 8, 28)
    _seed(db, "DE", calculation_date)
    destination = tmp_path / "markets/de/breadth/contributors"
    destination.mkdir(parents=True)
    (destination / "stale.json").write_text('{"stale": true}', encoding="utf-8")

    StaticBreadthContributorExporter().export(
        db,
        tmp_path,
        Path("markets/de"),
        _breadth_payload("DE", [calculation_date]),
    )

    assert not (destination / "stale.json").exists()
    assert (destination / "index.json").is_file()
