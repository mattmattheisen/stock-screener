from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from app.domain.markets.calendar_coverage import CalendarSource
from app.domain.markets.calendar_policy import CalendarProvider
from app.domain.markets.catalog import MarketCatalog, get_market_catalog
from app.services.calendar_manifest_generation import (
    CalendarManifestGenerationError,
    CalendarManifestGenerator,
)


class _ProviderCalendar:
    def __init__(self, sessions: tuple[date, ...]) -> None:
        self.sessions = tuple(pd.Timestamp(day) for day in sessions)

    def sessions_in_range(self, start, end):
        return tuple(
            session
            for session in self.sessions
            if start.date() <= session.date() <= end.date()
        )


class _BoundedProviderCalendar:
    def sessions_in_range(self, _start, _end):
        raise ValueError("Requested end is later than the last session available")


class _StrictRangeProviderCalendar:
    first_session = pd.Timestamp("2027-01-04")
    last_session = pd.Timestamp("2027-12-30")

    def sessions_in_range(self, start, end):
        if start < self.first_session or end > self.last_session:
            raise ValueError("range endpoint outside provider session bounds")
        return (self.first_session, self.last_session)


def _kr_catalog() -> MarketCatalog:
    return MarketCatalog((get_market_catalog().get("KR"),))


def _source() -> CalendarSource:
    return CalendarSource(
        name="Pinned exchange-calendars schedule",
        url="https://github.com/gerrymanoim/exchange_calendars",
        checked_at=date(2026, 8, 8),
    )


def _generator(provider_calendar) -> CalendarManifestGenerator:
    return CalendarManifestGenerator(
        market_catalog=_kr_catalog(),
        calendar_providers={
            CalendarProvider.EXCHANGE_CALENDARS: lambda _name: provider_calendar,
        },
        provider_versions={CalendarProvider.EXCHANGE_CALENDARS: "4.11.1"},
    )


def test_generator_writes_sorted_deterministic_provisional_json(
    tmp_path: Path,
) -> None:
    generator = _generator(
        _ProviderCalendar(
            (
                date(2027, 1, 5),
                date(2027, 1, 4),
                date(2028, 1, 3),
                date(2029, 1, 2),
                date(2030, 1, 2),
            )
        )
    )

    paths = generator.generate_provisional_years(
        tmp_path,
        market="KR",
        start_year=2027,
        through_year=2030,
        source=_source(),
    )

    assert [path.name for path in paths] == [
        "2027.provisional.json",
        "2028.provisional.json",
        "2029.provisional.json",
        "2030.provisional.json",
    ]
    text = paths[0].read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == {
        "market": "KR",
        "mic": "XKRX",
        "year": 2027,
        "status": "provisional",
        "source": {
            "name": "Pinned exchange-calendars schedule",
            "url": "https://github.com/gerrymanoim/exchange_calendars",
            "checked_at": "2026-08-08",
        },
        "provider": "exchange_calendars",
        "provider_version": "4.11.1",
        "sessions": ["2027-01-04", "2027-01-05"],
    }


def test_generator_does_not_turn_provider_bounds_errors_into_weekdays(
    tmp_path: Path,
) -> None:
    generator = _generator(_BoundedProviderCalendar())

    with pytest.raises(CalendarManifestGenerationError, match="provider schedule"):
        generator.generate_provisional_years(
            tmp_path,
            market="KR",
            start_year=2027,
            through_year=2030,
            source=_source(),
        )

    assert not list(tmp_path.rglob("*.json"))


def test_generator_clamps_calendar_year_to_provider_session_bounds(
    tmp_path: Path,
) -> None:
    generator = _generator(_StrictRangeProviderCalendar())

    (output,) = generator.generate_provisional_years(
        tmp_path,
        market="KR",
        start_year=2027,
        through_year=2027,
        source=_source(),
    )

    assert json.loads(output.read_text(encoding="utf-8"))["sessions"] == [
        "2027-01-04",
        "2027-12-30",
    ]


def test_generator_refuses_to_overwrite_official_year(tmp_path: Path) -> None:
    market_dir = tmp_path / "kr"
    market_dir.mkdir()
    official_path = market_dir / "2027.json"
    official_path.write_text('{"status":"official"}\n', encoding="utf-8")
    generator = _generator(_ProviderCalendar((date(2027, 1, 4),)))

    with pytest.raises(CalendarManifestGenerationError, match="official"):
        generator.generate_provisional_years(
            tmp_path,
            market="KR",
            start_year=2027,
            through_year=2027,
            source=_source(),
        )

    assert official_path.read_text(encoding="utf-8") == '{"status":"official"}\n'


def test_generator_check_mode_reports_drift_without_writing(tmp_path: Path) -> None:
    generator = _generator(_ProviderCalendar((date(2027, 1, 4),)))

    with pytest.raises(CalendarManifestGenerationError, match="drift"):
        generator.generate_provisional_years(
            tmp_path,
            market="KR",
            start_year=2027,
            through_year=2027,
            source=_source(),
            check=True,
        )

    assert not list(tmp_path.rglob("*.json"))


def test_generator_check_mode_accepts_matching_file(tmp_path: Path) -> None:
    generator = _generator(_ProviderCalendar((date(2027, 1, 4),)))
    generator.generate_provisional_years(
        tmp_path,
        market="KR",
        start_year=2027,
        through_year=2027,
        source=_source(),
    )

    checked = generator.generate_provisional_years(
        tmp_path,
        market="KR",
        start_year=2027,
        through_year=2027,
        source=_source(),
        check=True,
    )

    assert checked == (tmp_path / "kr" / "2027.provisional.json",)


def test_generator_imports_explicit_official_sessions(tmp_path: Path) -> None:
    generator = _generator(_ProviderCalendar(()))

    output = generator.import_official_year(
        tmp_path,
        market="KR",
        year=2027,
        sessions=(date(2027, 1, 5), date(2027, 1, 4)),
        source=CalendarSource(
            name="Korea Exchange 2027 market calendar",
            url="https://global.krx.co.kr/official-2027",
            checked_at=date(2026, 12, 1),
        ),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "official"
    assert payload["sessions"] == ["2027-01-04", "2027-01-05"]
    assert "provider" not in payload
    assert output.name == "2027.json"


def test_generator_module_import_does_not_require_database_settings() -> None:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)

    result = subprocess.run(
        [sys.executable, "-c", "import app.services.calendar_manifest_generation"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
