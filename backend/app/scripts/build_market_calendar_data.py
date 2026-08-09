"""Rebuild the checked-in Market calendar data set from reviewed inputs."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path

import pandas_market_calendars as pmc
from dateutil.easter import easter

from app.domain.markets.calendar_coverage import CalendarSource
from app.domain.markets.catalog import get_market_catalog
from app.domain.markets.reviewed_calendar_input import ReviewedCalendarInput
from app.services.calendar_manifest_generation import CalendarManifestGenerator


FIRST_YEAR = 2026
THROUGH_YEAR = 2030
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "market_calendars"
DEFAULT_REVIEWED_INPUT = (
    DEFAULT_ROOT / "inputs" / "reviewed_official_calendars.json"
)


def _weekdays(year: int) -> tuple[date, ...]:
    sessions = []
    candidate = date(year, 1, 1)
    while candidate <= date(year, 12, 31):
        if candidate.weekday() < 5:
            sessions.append(candidate)
        candidate += timedelta(days=1)
    return tuple(sessions)


def _singapore_provisional_sessions(year: int) -> tuple[date, ...]:
    """Planning calendar with deterministic fixed-date and Good Friday rules.

    Variable lunar/religious holidays remain provisional assumptions and are
    replaced when SGX publishes the official annual schedule.
    """
    closures = {
        date(year, 1, 1),
        date(year, 5, 1),
        date(year, 8, 9),
        date(year, 12, 25),
        easter(year) - timedelta(days=2),
    }
    closures.update(
        holiday + timedelta(days=1)
        for holiday in tuple(closures)
        if holiday.weekday() == 6
    )
    return tuple(day for day in _weekdays(year) if day not in closures)


def _provider_source(provider: str, *, checked_at: date) -> CalendarSource:
    return CalendarSource(
        name=f"Pinned {provider} generated schedule",
        url=(
            "https://github.com/gerrymanoim/exchange_calendars"
            if provider == "exchange_calendars"
            else "https://github.com/rsheftel/pandas_market_calendars"
        ),
        checked_at=checked_at,
    )


def _render(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _write_or_check(path: Path, content: str, *, check: bool) -> None:
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"calendar data drift detected: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build(
    root: Path,
    *,
    check: bool = False,
    reviewed_input: Path = DEFAULT_REVIEWED_INPUT,
) -> None:
    catalog = get_market_catalog()
    reviewed = ReviewedCalendarInput.load(
        reviewed_input,
        market_catalog=catalog,
        first_year=FIRST_YEAR,
    )
    generator = CalendarManifestGenerator(market_catalog=catalog)
    index_markets: dict[str, object] = {}

    for market in catalog.supported_market_codes():
        entry = catalog.get(market)
        source = reviewed.source_for(market)
        official_through = reviewed.official_through(market)
        years: dict[str, str] = {}
        for year in range(FIRST_YEAR, THROUGH_YEAR + 1):
            if year <= official_through:
                output = generator.import_official_closures(
                    root,
                    market=market,
                    year=year,
                    closures=reviewed.closures_for(market, year),
                    source=source,
                    check=check,
                )
            elif market == "CN":
                calendar = pmc.get_calendar("SSE")
                schedule = calendar.schedule(
                    start_date=f"{year}-01-01",
                    end_date=f"{year}-12-31",
                )
                output = generator.import_provisional_year(
                    root,
                    market=market,
                    year=year,
                    sessions=tuple(index.date() for index in schedule.index),
                    source=_provider_source(
                        "pandas_market_calendars",
                        checked_at=reviewed.checked_at,
                    ),
                    provider="pandas_market_calendars",
                    provider_version="5.3.0",
                    check=check,
                )
            elif market == "SG":
                output = generator.import_provisional_year(
                    root,
                    market=market,
                    year=year,
                    sessions=_singapore_provisional_sessions(year),
                    source=CalendarSource(
                        name=(
                            "Project fixed-holiday and Good Friday Singapore "
                            "planning calendar; variable holidays provisional"
                        ),
                        url="https://www.sgx.com/stock-exchange/clearing-information",
                        checked_at=reviewed.checked_at,
                    ),
                    provider="project_singapore_holiday_rules",
                    provider_version="2",
                    check=check,
                )
            else:
                facts = entry.primary_mic_facts
                output = generator.generate_provisional_years(
                    root,
                    market=market,
                    start_year=year,
                    through_year=year,
                    source=_provider_source(
                        facts.calendar_provider.value,
                        checked_at=reviewed.checked_at,
                    ),
                    check=check,
                )[0]
            years[str(year)] = str(output.relative_to(root))

        index_markets[market] = {
            "mic": entry.primary_mic,
            "verified_through": f"{official_through}-12-31",
            "source": {
                "name": source.name,
                "url": source.url,
                "checked_at": reviewed.checked_at.isoformat(),
            },
            "years": years,
        }

    index = {
        "schema_version": 1,
        "generated_at": reviewed.checked_at.isoformat(),
        "provisional_through": f"{THROUGH_YEAR}-12-31",
        "markets": index_markets,
    }
    _write_or_check(root / "index.json", _render(index), check=check)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--reviewed-input",
        type=Path,
        default=DEFAULT_REVIEWED_INPUT,
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    build(
        args.root,
        check=args.check,
        reviewed_input=args.reviewed_input,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
