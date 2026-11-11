from dataclasses import replace
from datetime import datetime, timezone

import pytest

from research.canslim_adaptive_entry_study.evidence import Evidence, ResearchSnapshot
from research.canslim_adaptive_entry_study.signal_ledger import build_ledger, incremental_eligibility


AT = datetime(2026, 10, 29, 21, tzinfo=timezone.utc)


def ev(value, source="verified"):
    return Evidence(value, AT, source)


def snap(*, close=87.0, rs=82.0, market="supportive"):
    return ResearchSnapshot(
        as_of=AT, close=ev(close), rolling_52w_high=ev(100.0),
        proprietary_rs=ev(rs, "licensed_ibd_rs"),
        market_state=ev(market), c_pass=ev(True), a_pass=ev(True),
        s_pass=ev(True), i_pass=ev(True), stock_strength_confirmed=ev(True),
    )


def test_variant_attribution():
    rows = build_ledger([("XYZ", snap())])
    assert [r.variant for r in rows] == list("ABCDE")
    assert [r.status for r in rows] == ["FAIL", "FAIL", "PASS", "FAIL", "PASS"]
    counts = incremental_eligibility(rows)
    assert counts["C_extra_pass"] == 1
    assert counts["E_extra_pass"] == 1
    assert counts["D_extra_pass"] == 0


def test_conditional_is_not_a_full_pass():
    rows = build_ledger([("XYZ", snap(close=95, market="cautionary"))])
    assert [r.status for r in rows] == ["FAIL", "CONDITIONAL", "FAIL", "FAIL", "CONDITIONAL"]
    counts = incremental_eligibility(rows)
    assert counts["B_extra_conditional"] == 1
    assert counts["B_extra_pass"] == 0


def test_missing_proprietary_rs_does_not_create_extra_signals():
    s = replace(snap(), proprietary_rs=ev(99, "calculated_market_rs"))
    rows = build_ledger([("XYZ", s)])
    assert all(r.status == "UNAVAILABLE" for r in rows)
    assert not any(incremental_eligibility(rows).values())


def test_duplicate_rejected():
    with pytest.raises(ValueError):
        build_ledger([("XYZ", snap()), ("XYZ", snap())])


def test_order_is_deterministic():
    rows = build_ledger([("ZZZ", snap()), ("AAA", snap())])
    assert rows[0].symbol == "AAA"
    assert rows[5].symbol == "ZZZ"
