"""Point-in-time leakage and missing-data regression tests."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from research.canslim_adaptive_entry_study.evidence import Evidence, ResearchSnapshot, assess

AT = datetime(2026, 10, 29, 21, 0, tzinfo=timezone.utc)


def e(value, source="verified", when=AT):
    return Evidence(value, when, source)


def snapshot():
    return ResearchSnapshot(
        as_of=AT,
        close=e(95.0, "consolidated_daily_bar"),
        rolling_52w_high=e(100.0, "consolidated_daily_bar"),
        proprietary_rs=e(83.0, "licensed_ibd_rs"),
        market_state=e("supportive", "frozen_market_regime"),
        c_pass=e(True, "sec_filing"),
        a_pass=e(True, "sec_filing"),
        s_pass=e(True, "historical_ohlcv"),
        i_pass=e(True, "filing_timestamp"),
        stock_strength_confirmed=e(True, "historical_ohlcv"),
    )


def test_valid_snapshot():
    assert assess(snapshot()).status == "PASS"


def test_future_earnings_not_visible():
    s = snapshot()
    s = replace(s, c_pass=e(True, "sec_filing", AT + timedelta(days=1)))
    assert assess(s).status == "UNAVAILABLE"


def test_future_institutional_filing_not_visible():
    s = replace(snapshot(), i_pass=e(True, "13f", AT + timedelta(days=2)))
    assert assess(s).status == "UNAVAILABLE"


def test_nonlicensed_rs_never_passes():
    s = replace(snapshot(), proprietary_rs=e(95.0, "calculated_market_rs"))
    assert assess(s).status == "UNAVAILABLE"


def test_market_caution_requires_confirmed_strength():
    s = replace(snapshot(), market_state=e("cautionary"))
    assert assess(s, "B").status == "CONDITIONAL"
    assert assess(replace(s, stock_strength_confirmed=e(False)), "B").status == "FAIL"
    assert assess(replace(s, stock_strength_confirmed=e(None)), "B").status == "UNAVAILABLE"


def test_confirmed_downtrend_no_override():
    s = replace(snapshot(), market_state=e("confirmed_downtrend"))
    assert assess(s, "E").status == "FAIL"


def test_missing_gate_and_false_gate():
    s = snapshot()
    assert assess(replace(s, a_pass=e(None))).status == "UNAVAILABLE"
    assert assess(replace(s, a_pass=e(False))).status == "FAIL"


def test_unverified_market_never_passes():
    s = replace(snapshot(), market_state=e("supportive", when=AT + timedelta(hours=1)))
    assert assess(s).status == "UNAVAILABLE"
