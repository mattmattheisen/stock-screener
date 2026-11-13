"""Regression checks against real SQLAlchemy mappings in isolated SQLite tests.

Uses the repository's existing pytest SQLite fixtures, never production DB.
"""
from datetime import date

from app.models.stock import StockPrice
from app.services.stock_price_persistence import persist_stock_price_mappings


DAY = date(2026, 11, 11)


def _incoming(*, close=100.0, adj_close=None):
    return dict(symbol="MSFT", date=DAY, open=close,
                high=close + 1, low=close - 1, close=close,
                volume=1000, adj_close=adj_close)


def _insert_existing(session, *, close=100.0, adj_close=98.0):
    session.add(StockPrice(**_incoming(close=close, adj_close=adj_close)))
    session.flush()


def _saved(session):
    return session.query(StockPrice).filter(
        StockPrice.symbol == "MSFT", StockPrice.date == DAY
    ).one()


def test_new_row_missing_adjustment_stays_null(db_session):
    stats = persist_stock_price_mappings(
        db_session, {"MSFT": [_incoming(adj_close=None)]}
    )
    assert stats["inserted"] == 1
    assert _saved(db_session).adj_close is None


def test_matching_raw_close_keeps_old_adjusted_close(db_session):
    _insert_existing(db_session)
    stats = persist_stock_price_mappings(
        db_session, {"MSFT": [_incoming(adj_close=None)]}
    )
    db_session.expire_all()
    assert stats["updated"] == 1
    assert _saved(db_session).adj_close == 98.0


def test_changed_raw_close_does_not_keep_stale_adjustment(db_session):
    _insert_existing(db_session)
    persist_stock_price_mappings(
        db_session, {"MSFT": [_incoming(close=110.0, adj_close=None)]}
    )
    db_session.expire_all()
    assert _saved(db_session).close == 110.0
    assert _saved(db_session).adj_close is None


def test_valid_explicit_adjustment_replaces_old_value(db_session):
    _insert_existing(db_session)
    persist_stock_price_mappings(
        db_session, {"MSFT": [_incoming(adj_close=97.0)]}
    )
    db_session.expire_all()
    assert _saved(db_session).adj_close == 97.0
