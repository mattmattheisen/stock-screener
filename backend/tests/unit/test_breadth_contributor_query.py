from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.database import Base
from app.models.breadth_contributor import (
    MarketBreadthContributor,
    MarketBreadthContributorSnapshot,
)
from app.models.market_breadth import MarketBreadth
from app.services.breadth.contributor_query import (
    BreadthContributorSnapshotInconsistent,
    BreadthContributorSnapshotUnavailable,
    get_contributor_document,
    list_contributor_dates,
)
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


def _seed_snapshot(db, calculation_date: date, *, market: str = "US"):
    aggregate = MarketBreadth(
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
    snapshot = MarketBreadthContributorSnapshot(
        market=market,
        date=calculation_date,
        calculation_revision=3,
        schema_id="breadth-contributors-v1",
        contributors=[
            MarketBreadthContributor(
                symbol="AAA",
                company_name="Alpha",
                ibd_industry_group="Semiconductors",
                daily_change_pct=5.25,
                signals_json={"up_4pct": 5.25},
            )
        ],
    )
    db.add_all([aggregate, snapshot])
    db.commit()
    return aggregate, snapshot


def test_index_is_newest_first_limited_and_market_isolated():
    db = _db_session()
    first = date(2026, 7, 1)
    for offset in range(21):
        _seed_snapshot(db, first + timedelta(days=offset))
    _seed_snapshot(db, first + timedelta(days=40), market="CA")

    payload = list_contributor_dates(db, "US", limit=20)

    assert payload.schema == "breadth-contributors-v1"
    assert payload.market == "US"
    assert payload.calculation_revision == 3
    assert len(payload.dates) == 20
    assert payload.dates == tuple(
        first + timedelta(days=offset) for offset in range(20, 0, -1)
    )


def test_document_returns_frozen_contributor_values():
    db = _db_session()
    calculation_date = date(2026, 8, 28)
    _seed_snapshot(db, calculation_date)

    payload = get_contributor_document(db, "us", calculation_date)

    assert payload.market == "US"
    assert payload.date == calculation_date
    assert len(payload.contributors) == 1
    contributor = payload.contributors[0]
    assert contributor.symbol == "AAA"
    assert contributor.company_name == "Alpha"
    assert contributor.ibd_industry_group == "Semiconductors"
    assert contributor.signals == {"up_4pct": 5.25}


def test_document_distinguishes_unavailable_from_inconsistent():
    db = _db_session()
    calculation_date = date(2026, 8, 28)
    with pytest.raises(BreadthContributorSnapshotUnavailable):
        get_contributor_document(db, "US", calculation_date)

    aggregate, _snapshot = _seed_snapshot(db, calculation_date)
    aggregate.stocks_up_4pct = 2
    db.commit()

    with pytest.raises(BreadthContributorSnapshotInconsistent, match="stocks_up_4pct"):
        get_contributor_document(db, "US", calculation_date)


def test_index_omits_inconsistent_snapshot():
    db = _db_session()
    good_date = date(2026, 8, 27)
    bad_date = date(2026, 8, 28)
    _seed_snapshot(db, good_date)
    aggregate, _snapshot = _seed_snapshot(db, bad_date)
    aggregate.stocks_up_4pct = 2
    db.commit()

    assert list_contributor_dates(db, "US").dates == (good_date,)
