from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_operations_guide_documents_calendar_maintenance_contract():
    operations = (_PROJECT_ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8")
    required = (
        "annual/on-publication",
        "weekly audit",
        "180 / 90 / 60 / 30 / expired",
        "non-blocking",
        "requested calculation date",
        "verified_through",
        "official",
        "provisional",
        "audit_market_calendars",
        "inputs/reviewed_official_calendars.json",
        "build_market_calendar_data",
        "explicit empty array",
        "git diff -- backend/data/market_calendars",
        "first-party",
        "emergency closure",
        "no-bar data",
    )
    for phrase in required:
        assert phrase in operations


def test_live_guide_explains_calendar_warning_and_failure_behavior():
    live_guide = (_PROJECT_ROOT / "docs/LIVE_APP_GUIDE.md").read_text(
        encoding="utf-8"
    )

    assert "weekly" in live_guide
    assert "calendar" in live_guide
    assert "warnings do not block" in live_guide
    assert "requested calculation date" in live_guide
    assert "verified official coverage" in live_guide
