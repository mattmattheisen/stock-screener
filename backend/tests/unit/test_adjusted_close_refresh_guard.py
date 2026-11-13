from app.services.price_value_policy import protect_existing_adjusted_close


def test_preserves_usable_adjusted_close_when_refresh_missing():
    original = {"date": "2026-11-11", "adj_close": None, "close": 100.0}
    result = protect_existing_adjusted_close(original, 98.5)
    assert result["adj_close"] == 98.5
    assert original["adj_close"] is None


def test_accepts_new_adjusted_close_when_available():
    result = protect_existing_adjusted_close(
        {"adj_close": 98.25, "close": 100.0}, 97.5
    )
    assert result["adj_close"] == 98.25


def test_cannot_fabricate_adj_close_if_both_missing():
    result = protect_existing_adjusted_close(
        {"adj_close": None, "close": 100.0}, None
    )
    assert result["adj_close"] is None


def test_rejects_nan_incoming_and_keeps_valid_existing():
    result = protect_existing_adjusted_close({"adj_close": float("nan")}, 101.5)
    assert result["adj_close"] == 101.5


def test_does_not_claim_legacy_existing_value_verified():
    # Protection prevents data loss; source validation remains a separate gate.
    result = protect_existing_adjusted_close({"adj_close": None}, 100.0)
    assert result["adj_close"] == 100.0


def test_changed_raw_close_invalidates_existing_adjusted_value():
    result = protect_existing_adjusted_close(
        {"adj_close": None, "close": 101.0}, 98.5,
        existing_raw_close=100.0,
    )
    assert result["adj_close"] is None


def test_unchanged_raw_close_preserves_existing_adjusted_value():
    result = protect_existing_adjusted_close(
        {"adj_close": None, "close": 100.0}, 98.5,
        existing_raw_close=100.0,
    )
    assert result["adj_close"] == 98.5
