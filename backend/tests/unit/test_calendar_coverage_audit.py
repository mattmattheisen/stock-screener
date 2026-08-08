from datetime import date, timedelta
from types import MappingProxyType

import pytest

from app.domain.markets.calendar_coverage import (
    CalendarCoverageRegistry,
    CalendarSource,
    MarketCalendarCoverage,
)
from app.services.calendar_coverage_audit import (
    audit_calendar_coverage,
    github_actions_output,
    markdown_summary,
)


def _registry(*, remaining_days: int, provisional_year: int = 2030):
    as_of = date(2026, 8, 8)
    source = CalendarSource(
        name="Official Exchange",
        url="https://exchange.example/calendar?market=US",
        checked_at=date(2026, 8, 1),
    )
    coverage = MarketCalendarCoverage(
        market="US",
        mic="XNYS",
        verified_through=as_of + timedelta(days=remaining_days),
        source=source,
        annual=MappingProxyType({}),
    )
    return (
        CalendarCoverageRegistry(
            {"US": coverage},
            provisional_through=date(provisional_year, 12, 31),
            generated_at=as_of,
        ),
        as_of,
    )


@pytest.mark.parametrize(
    ("remaining", "status", "warning_count"),
    [
        (181, "ok", 0),
        (180, "expires-within-180-days", 1),
        (90, "expires-within-90-days", 1),
        (60, "expires-within-60-days", 1),
        (30, "expires-within-30-days", 1),
        (0, "expires-within-30-days", 1),
        (-1, "expired", 1),
    ],
)
def test_audit_uses_one_active_warning_band(remaining, status, warning_count):
    registry, as_of = _registry(remaining_days=remaining)

    result = audit_calendar_coverage(registry, as_of=as_of)

    assert result.rows[0].status == status
    assert result.rows[0].days_remaining == remaining
    assert len(result.warnings) == warning_count


def test_markdown_contains_operational_coverage_fields():
    registry, as_of = _registry(remaining_days=90)

    output = markdown_summary(audit_calendar_coverage(registry, as_of=as_of))

    assert "Market" in output
    assert "MIC" in output
    assert "Verified through" in output
    assert "Days remaining" in output
    assert "Status" in output
    assert "Source" in output
    assert "US" in output
    assert "XNYS" in output
    assert "Official Exchange" in output


def test_github_actions_output_escapes_annotations_and_appends_summary():
    registry, as_of = _registry(remaining_days=30)

    output = github_actions_output(audit_calendar_coverage(registry, as_of=as_of))

    assert output.startswith("::warning::")
    assert "%3F" not in output
    assert "%0A" not in output.splitlines()[0]
    assert "| Market | MIC |" in output


def test_short_provisional_horizon_warns_without_invalidating_audit():
    registry, as_of = _registry(remaining_days=181, provisional_year=2029)

    result = audit_calendar_coverage(registry, as_of=as_of)

    assert result.rows[0].status == "ok"
    assert len(result.warnings) == 1
    assert "provisional" in result.warnings[0].lower()
