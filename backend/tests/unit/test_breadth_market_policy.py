from __future__ import annotations

import pytest

from app.domain.markets.catalog import get_market_catalog
from app.services.breadth.market_policy import (
    BREADTH_MARKET_POLICIES,
    get_breadth_market_policy,
)
from app.services.breadth.types import (
    CURRENT_BREADTH_CALCULATION_REVISION,
    BreadthFormulaPolicy,
    BreadthMarketPolicy,
)


def test_breadth_market_policy_keys_match_catalog_capability() -> None:
    expected = set(get_market_catalog().market_codes_with_capability("breadth"))

    assert set(BREADTH_MARKET_POLICIES) == expected


@pytest.mark.parametrize(
    ("market", "expected"),
    (
        ("US", BreadthMarketPolicy("US", "USD", 250_000, 100_000, 5.00)),
        ("CA", BreadthMarketPolicy("CA", "CAD", 5_000, 5_000, 0.30)),
        ("DE", BreadthMarketPolicy("DE", "EUR", 5_000, 300, 8.00)),
        ("HK", BreadthMarketPolicy("HK", "HKD", 20_000, 150_000, 0.20)),
        ("IN", BreadthMarketPolicy("IN", "INR", 100_000, 15_000, 15.00)),
        ("JP", BreadthMarketPolicy("JP", "JPY", 8_000_000, 50_000, 500.00)),
        ("KR", BreadthMarketPolicy("KR", "KRW", 100_000_000, 50_000, 2_000.00)),
        ("TW", BreadthMarketPolicy("TW", "TWD", 3_500_000, 400_000, 20.00)),
        ("CN", BreadthMarketPolicy("CN", "CNY", 50_000_000, 10_000_000, 5.00)),
    ),
)
def test_breadth_market_policies_store_selected_local_thresholds(
    market: str,
    expected: BreadthMarketPolicy,
) -> None:
    assert get_breadth_market_policy(market.lower()) == expected


@pytest.mark.parametrize("market", ("AU", "SG", "MY", "", "XX"))
def test_unsupported_market_policy_lookup_fails_closed(market: str) -> None:
    rendered = market or "<missing>"

    with pytest.raises(
        ValueError,
        match=f"Breadth is not supported for market {rendered}",
    ):
        get_breadth_market_policy(market)


def test_formula_policy_contains_only_formula_wide_settings() -> None:
    policy = BreadthFormulaPolicy()

    assert policy.calculation_revision == 3
    assert policy.atr_period == 14
    assert policy.atr_extension_threshold == 10.0
    assert not hasattr(policy, "min_adtv_usd")
    assert not hasattr(policy, "min_daily_volume")
    assert not hasattr(policy, "min_month_reference_price_usd")
    assert not hasattr(policy, "fx_max_age_days")


def test_current_breadth_revision_is_three() -> None:
    assert CURRENT_BREADTH_CALCULATION_REVISION == 3
