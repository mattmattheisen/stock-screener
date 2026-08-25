from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.market_breadth import MarketBreadth
from app.services.breadth.rebuild import BreadthRebuildService
from app.services.breadth.types import (
    BreadthDailyResult,
    BreadthEligibilityCounts,
    BreadthIndicatorValues,
)


def _result(day: date) -> BreadthDailyResult:
    return BreadthDailyResult(
        market="US",
        calculation_date=day,
        values=BreadthIndicatorValues(
            stocks_up_4pct=8,
            stocks_down_4pct=2,
            advancing_count=60,
            declining_count=35,
            unchanged_count=5,
            t2108_count=50,
            t2108_pct=50.0,
        ),
        eligibility=BreadthEligibilityCounts(
            advance_decline_eligible_count=100,
            stockbee_daily_eligible_count=90,
            stockbee_month_eligible_count=80,
            stockbee_34day_eligible_count=75,
            stockbee_quarter_eligible_count=70,
            t2108_eligible_count=100,
            high_low_52week_eligible_count=65,
            atr_extension_eligible_count=85,
        ),
        broad_universe_count=110,
        eligibility_signature="a" * 64,
        stockbee_eligibility_signature="b" * 64,
    )


def test_revision_cutover_replaces_legacy_rows_and_preserves_unrelated_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cutover.sqlite'}")
    Base.metadata.create_all(engine, tables=[MarketBreadth.__table__])
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE unrelated (id INTEGER PRIMARY KEY, value TEXT)")
        )
        connection.execute(text("INSERT INTO unrelated (id, value) VALUES (1, 'keep')"))
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(
            MarketBreadth(
                market="US",
                date=date(2026, 8, 20),
                stocks_up_4pct=99,
                stocks_down_4pct=1,
                stocks_up_25pct_quarter=0,
                stocks_down_25pct_quarter=0,
                stocks_up_25pct_month=0,
                stocks_down_25pct_month=0,
                stocks_up_50pct_month=0,
                stocks_down_50pct_month=0,
                stocks_up_13pct_34days=0,
                stocks_down_13pct_34days=0,
                total_stocks_scanned=100,
            )
        )
        db.commit()
        service = BreadthRebuildService(db)
        service.recreate_staging()
        service.stage_results((_result(date(2026, 8, 21)),))

        report = service.validate()
        assert report["valid"] is True
        service.activate()

        rows = db.query(MarketBreadth).all()
        assert [(row.date, row.calculation_revision) for row in rows] == [
            (date(2026, 8, 21), 2)
        ]
        unrelated = db.execute(
            text("SELECT value FROM unrelated WHERE id = 1")
        ).scalar()
        assert unrelated == "keep"

    engine.dispose()
