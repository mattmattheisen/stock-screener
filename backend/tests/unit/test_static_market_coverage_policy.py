import pytest

from app.services.static_market_coverage_policy import (
    market_current_price_min_coverage,
    static_breadth_history_min_coverage,
    static_daily_price_bundle_min_coverage,
)


def test_static_coverage_policy_keeps_us_on_global_default():
    assert market_current_price_min_coverage("US") == pytest.approx(0.90)
    assert static_daily_price_bundle_min_coverage("US") == pytest.approx(0.90)
    assert static_breadth_history_min_coverage("US") == pytest.approx(0.90)


@pytest.mark.parametrize(
    ("market", "expected"),
    [
        ("CA", 0.70),
        ("DE", 0.84),
        ("HK", 0.75),
        ("IN", 0.45),
        ("MY", 0.85),
        ("SG", 0.55),
        ("TW", 0.50),
    ],
)
def test_static_coverage_policy_reuses_market_specific_static_floors(
    market,
    expected,
):
    assert market_current_price_min_coverage(market) == pytest.approx(expected)
    assert static_daily_price_bundle_min_coverage(market) == pytest.approx(expected)
    assert static_breadth_history_min_coverage(market) == pytest.approx(expected)
