"""Deterministic research comparator checks; run with pytest."""
from dataclasses import replace
from research.canslim_adaptive_entry_study.comparator import Observation, evaluate


def sample(**changes):
    base = Observation(90, 100, 82, True, "supportive", True)
    return replace(base, **changes)


def test_baseline_boundary():
    assert evaluate(sample()).status == "PASS"
    assert evaluate(sample(close=89.99)).status == "FAIL"


def test_n_relaxation_is_isolated():
    o = sample(close=87)
    assert evaluate(o, "A").status == "FAIL"
    assert evaluate(o, "C").status == "PASS"


def test_rs_relaxation_is_isolated():
    o = sample(rs_rating=77)
    assert evaluate(o, "A").status == "FAIL"
    assert evaluate(o, "D").status == "PASS"


def test_caution_only_reduced_size():
    o = sample(market_state="cautionary")
    assert evaluate(o, "A").status == "FAIL"
    d = evaluate(o, "B")
    assert (d.status, d.allocation_fraction) == ("CONDITIONAL", 0.25)
    assert evaluate(sample(market_state="confirmed_downtrend"), "B").status == "FAIL"


def test_missing_data_never_passes():
    assert evaluate(sample(rs_source_verified=False), "E").status == "UNAVAILABLE"
    assert evaluate(sample(other_gates_pass=None), "E").status == "UNAVAILABLE"
    assert evaluate(sample(market_state=None), "E").status == "UNAVAILABLE"


def test_invalid_price_history_rejected():
    assert evaluate(sample(close=101), "E").status == "UNAVAILABLE"
