import pytest

from research.canslim_adaptive_entry_study.unusual_whales_adapter import adapt_daily_rows


def row(day="2026-11-10", **changes):
    result = {"ticker": "ANET", "date": day, "open": "180", "high": "190",
              "low": "178", "close": "185", "call_volume": 12000,
              "put_volume": 9000}
    result.update(changes)
    return result


def test_options_volume_never_substitutes_for_stock_volume():
    bars, quality = adapt_daily_rows([row()], "ANET")
    assert bars[0]["share_volume"] is None
    assert quality["share_volume_available"] is False
    assert quality["full_canslim_backtest_ready"] is False
    assert bars[0]["adjustment_basis"] == "unverified"


def test_chronological_and_duplicate_rejection():
    bars, _ = adapt_daily_rows([row("2026-11-11"), row("2026-11-10")], "ANET")
    assert [b["date"] for b in bars] == ["2026-11-10", "2026-11-11"]
    with pytest.raises(ValueError, match="duplicate"):
        adapt_daily_rows([row(), row()], "ANET")


def test_ticker_and_price_validation():
    with pytest.raises(ValueError, match="ticker mismatch"):
        adapt_daily_rows([row(ticker="MSFT")], "ANET")
    with pytest.raises(ValueError, match="inconsistent"):
        adapt_daily_rows([row(high="170")], "ANET")
    with pytest.raises(ValueError, match="invalid"):
        adapt_daily_rows([row(close="nan")], "ANET")
