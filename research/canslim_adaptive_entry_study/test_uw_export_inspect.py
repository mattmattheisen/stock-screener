import pytest

from research.canslim_adaptive_entry_study.uw_export_inspect import inspect_export


def record(date):
    return {"ticker": "ANET", "date": date, "open": "100",
            "high": "110", "low": "95", "close": "105",
            "call_volume": 12000, "put_volume": 8000}


def test_inspect_export_fails_closed():
    result = inspect_export({"result": [record("2026-11-10")]}, "ANET")
    assert result["rows"] == 1
    assert result["missing_share_volume_rows"] == 1
    assert result["price_only_52w_high_possible"] is False
    assert result["full_canslim_backtest_ready"] is False


def test_export_requires_known_shape():
    with pytest.raises(ValueError):
        inspect_export({"unknown": []}, "ANET")
