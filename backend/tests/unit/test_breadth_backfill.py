from __future__ import annotations

from datetime import date

import pytest

from app.services.breadth_backfill import BreadthBackfillPlan
from app.services.static_breadth_eligibility import (
    static_breadth_eligibility_signature,
)


def test_backfill_plan_canonicalizes_symbols_and_derives_signature():
    calculation_date = date(2026, 3, 20)
    expected_signature = static_breadth_eligibility_signature(("AAA", "BBB"))

    plan = BreadthBackfillPlan.from_legacy(
        dates=[calculation_date],
        eligible_symbols_by_date={
            calculation_date: ("BBB", "AAA", "AAA"),
        },
        eligibility_signatures_by_date={
            calculation_date: expected_signature,
        },
    )

    universe = plan.universe_for(calculation_date)
    assert universe is not None
    assert universe.symbols == ("AAA", "BBB")
    assert universe.eligibility_signature == expected_signature


@pytest.mark.parametrize(
    ("eligible_symbols_by_date", "eligibility_signatures_by_date"),
    [
        ({date(2026, 3, 20): ("AAA",)}, None),
        (None, {date(2026, 3, 20): "signature"}),
    ],
)
def test_backfill_plan_rejects_half_supplied_legacy_contract(
    eligible_symbols_by_date,
    eligibility_signatures_by_date,
):
    with pytest.raises(ValueError, match="must be supplied together"):
        BreadthBackfillPlan.from_legacy(
            dates=[date(2026, 3, 20)],
            eligible_symbols_by_date=eligible_symbols_by_date,
            eligibility_signatures_by_date=eligibility_signatures_by_date,
        )


def test_backfill_plan_rejects_missing_requested_date():
    with pytest.raises(ValueError, match="missing for 2026-03-21"):
        BreadthBackfillPlan.from_legacy(
            dates=[date(2026, 3, 20), date(2026, 3, 21)],
            eligible_symbols_by_date={
                date(2026, 3, 20): ("AAA",),
            },
            eligibility_signatures_by_date={
                date(2026, 3, 20): static_breadth_eligibility_signature(("AAA",)),
            },
        )


def test_backfill_plan_rejects_signature_for_different_symbols():
    calculation_date = date(2026, 3, 20)

    with pytest.raises(ValueError, match="signature does not match"):
        BreadthBackfillPlan.from_legacy(
            dates=[calculation_date],
            eligible_symbols_by_date={calculation_date: ("AAA",)},
            eligibility_signatures_by_date={
                calculation_date: static_breadth_eligibility_signature(("BBB",)),
            },
        )


def test_backfill_plan_without_explicit_eligibility_preserves_legacy_mode():
    calculation_date = date(2026, 3, 20)

    plan = BreadthBackfillPlan.from_legacy(
        dates=[calculation_date],
        eligible_symbols_by_date=None,
        eligibility_signatures_by_date=None,
    )

    assert plan.dates == (calculation_date,)
    assert plan.universe_for(calculation_date) is None
