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
from app.services.calendar_manifest_generation import CalendarManifestGenerator


CHECKED_AT = date(2026, 8, 8)
FIRST_YEAR = 2026
THROUGH_YEAR = 2030
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "market_calendars"

OFFICIAL_SOURCES = {
    "US": (
        "NYSE Holidays & Trading Hours",
        "https://www.nyse.com/trade/hours-calendars",
        2028,
    ),
    "HK": (
        "HKEX Hong Kong Securities Market Holiday Schedule for 2026",
        "https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf",
        2026,
    ),
    "IN": (
        "NSE Market Timings & Holidays",
        "https://www.nseindia.com/resources/exchange-communication-holidays",
        2026,
    ),
    "JP": (
        "Japan Exchange Group Market Holidays",
        "https://www.jpx.co.jp/english/corporate/about-jpx/calendar/index.html",
        2027,
    ),
    "KR": (
        "Korea Exchange Market Closing (Holiday)",
        "https://global.krx.co.kr/contents/GLB/05/0501/0501110000/GLB0501110000.jsp",
        2026,
    ),
    "TW": (
        "Taiwan Stock Exchange Holiday Schedule",
        "https://www.twse.com.tw/en/trading/holiday.html",
        2026,
    ),
    "CN": (
        "Shenzhen Stock Exchange Stock Market Holiday Schedule 2026",
        "https://www.szse.cn/www/English/services/trading/calendar/",
        2026,
    ),
    "CA": (
        "TMX TSX Calendar",
        "https://www.tsx.com/en/trading/calendars-and-trading-hours/calendar",
        2026,
    ),
    "DE": (
        "Deutsche Börse Trading Calendar",
        "https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours",
        2030,
    ),
    "SG": (
        "Singapore Exchange Clearing Information and Holidays",
        "https://www.sgx.com/stock-exchange/clearing-information",
        2026,
    ),
    "AU": (
        "ASX Trade Calendar",
        "https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar",
        2026,
    ),
    "MY": (
        "Bursa Malaysia Market Trading Days and Public Holidays",
        "https://www.bursamalaysia.com/market_information/market_statistic/market_holidays",
        2026,
    ),
}

def _reviewed_dates(value: str) -> frozenset[date]:
    return frozenset(date.fromisoformat(token) for token in value.split())


# Complete weekday-closure inputs transcribed and reviewed against the cited
# first-party publications. Official manifests are built from these inputs,
# never from provider session output.
REVIEWED_OFFICIAL_CLOSURES = {
    ("AU", 2026): _reviewed_dates(
        "2026-01-01 2026-01-26 2026-04-03 2026-04-06 2026-06-08 "
        "2026-12-25 2026-12-28"
    ),
    ("CA", 2026): _reviewed_dates(
        "2026-01-01 2026-02-16 2026-04-03 2026-05-18 2026-07-01 "
        "2026-08-03 2026-09-07 2026-10-12 2026-12-25 2026-12-28"
    ),
    ("CN", 2026): _reviewed_dates(
        "2026-01-01 2026-01-02 2026-02-16 2026-02-17 2026-02-18 "
        "2026-02-19 2026-02-20 2026-02-23 2026-04-06 2026-05-01 "
        "2026-05-04 2026-05-05 2026-06-19 2026-09-25 2026-10-01 "
        "2026-10-02 2026-10-05 2026-10-06 2026-10-07"
    ),
    ("DE", 2026): _reviewed_dates(
        "2026-01-01 2026-04-03 2026-04-06 2026-05-01 2026-12-24 "
        "2026-12-25 2026-12-31"
    ),
    ("DE", 2027): _reviewed_dates(
        "2027-01-01 2027-03-26 2027-03-29 2027-12-24 2027-12-31"
    ),
    ("DE", 2028): _reviewed_dates(
        "2028-04-14 2028-04-17 2028-05-01 2028-12-25 2028-12-26"
    ),
    ("DE", 2029): _reviewed_dates(
        "2029-01-01 2029-03-30 2029-04-02 2029-05-01 2029-12-24 "
        "2029-12-25 2029-12-26 2029-12-31"
    ),
    ("DE", 2030): _reviewed_dates(
        "2030-01-01 2030-04-19 2030-04-22 2030-05-01 2030-12-24 "
        "2030-12-25 2030-12-26 2030-12-31"
    ),
    ("HK", 2026): _reviewed_dates(
        "2026-01-01 2026-02-17 2026-02-18 2026-02-19 2026-04-03 "
        "2026-04-06 2026-04-07 2026-05-01 2026-05-25 2026-06-19 "
        "2026-07-01 2026-10-01 2026-10-19 2026-12-25"
    ),
    ("IN", 2026): _reviewed_dates(
        "2026-01-26 2026-03-03 2026-03-26 2026-03-31 2026-04-03 "
        "2026-04-14 2026-05-01 2026-05-28 2026-06-26 2026-09-14 "
        "2026-10-02 2026-10-20 2026-11-10 2026-11-24 2026-12-25"
    ),
    ("JP", 2026): _reviewed_dates(
        "2026-01-01 2026-01-02 2026-01-12 2026-02-11 2026-02-23 "
        "2026-03-20 2026-04-29 2026-05-04 2026-05-05 2026-05-06 "
        "2026-07-20 2026-08-11 2026-09-21 2026-09-22 2026-09-23 "
        "2026-10-12 2026-11-03 2026-11-23 2026-12-31"
    ),
    ("JP", 2027): _reviewed_dates(
        "2027-01-01 2027-01-11 2027-02-11 2027-02-23 2027-03-22 "
        "2027-04-29 2027-05-03 2027-05-04 2027-05-05 2027-07-19 "
        "2027-08-11 2027-09-20 2027-09-23 2027-10-11 2027-11-03 "
        "2027-11-23 2027-12-31"
    ),
    ("KR", 2026): _reviewed_dates(
        "2026-01-01 2026-02-16 2026-02-17 2026-02-18 2026-03-02 "
        "2026-05-01 2026-05-05 2026-05-25 2026-06-03 2026-07-17 "
        "2026-08-17 2026-09-24 2026-09-25 2026-10-05 2026-10-09 "
        "2026-12-25 2026-12-31"
    ),
    ("MY", 2026): _reviewed_dates(
        "2026-01-01 2026-02-02 2026-02-17 2026-02-18 2026-03-06 "
        "2026-03-20 2026-03-23 2026-05-01 2026-05-27 2026-06-01 "
        "2026-06-16 2026-06-17 2026-08-25 2026-08-31 2026-09-16 "
        "2026-12-25"
    ),
    ("SG", 2026): _reviewed_dates(
        "2026-01-01 2026-02-17 2026-02-18 2026-04-03 2026-05-01 "
        "2026-05-27 2026-06-01 2026-08-10 2026-11-09 2026-12-25"
    ),
    ("TW", 2026): _reviewed_dates(
        "2026-01-01 2026-01-02 2026-02-12 2026-02-13 2026-02-16 "
        "2026-02-17 2026-02-18 2026-02-19 2026-02-20 2026-02-27 "
        "2026-04-03 2026-04-06 2026-05-01 2026-06-19 2026-09-25 "
        "2026-09-28 2026-10-09 2026-10-26 2026-12-25"
    ),
    ("US", 2026): _reviewed_dates(
        "2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 "
        "2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25"
    ),
    ("US", 2027): _reviewed_dates(
        "2027-01-01 2027-01-18 2027-02-15 2027-03-26 2027-05-31 "
        "2027-06-18 2027-07-05 2027-09-06 2027-11-25 2027-12-24"
    ),
    ("US", 2028): _reviewed_dates(
        "2028-01-17 2028-02-21 2028-04-14 2028-05-29 2028-06-19 "
        "2028-07-04 2028-09-04 2028-11-23 2028-12-25"
    ),
}


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


def _source(market: str) -> CalendarSource:
    name, url, _through = OFFICIAL_SOURCES[market]
    return CalendarSource(name=name, url=url, checked_at=CHECKED_AT)


def _provider_source(provider: str) -> CalendarSource:
    return CalendarSource(
        name=f"Pinned {provider} generated schedule",
        url=(
            "https://github.com/gerrymanoim/exchange_calendars"
            if provider == "exchange_calendars"
            else "https://github.com/rsheftel/pandas_market_calendars"
        ),
        checked_at=CHECKED_AT,
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


def build(root: Path, *, check: bool = False) -> None:
    catalog = get_market_catalog()
    generator = CalendarManifestGenerator(market_catalog=catalog)
    index_markets: dict[str, object] = {}

    for market in catalog.supported_market_codes():
        entry = catalog.get(market)
        source_name, source_url, official_through = OFFICIAL_SOURCES[market]
        years: dict[str, str] = {}
        for year in range(FIRST_YEAR, THROUGH_YEAR + 1):
            if year <= official_through:
                try:
                    official_closures = REVIEWED_OFFICIAL_CLOSURES[(market, year)]
                except KeyError as exc:
                    raise RuntimeError(
                        f"missing reviewed official closure input for {market} {year}"
                    ) from exc
                output = generator.import_official_closures(
                    root,
                    market=market,
                    year=year,
                    closures=official_closures,
                    source=_source(market),
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
                    source=_provider_source("pandas_market_calendars"),
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
                        checked_at=CHECKED_AT,
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
                    source=_provider_source(facts.calendar_provider.value),
                    check=check,
                )[0]
            years[str(year)] = str(output.relative_to(root))

        index_markets[market] = {
            "mic": entry.primary_mic,
            "verified_through": f"{official_through}-12-31",
            "source": {
                "name": source_name,
                "url": source_url,
                "checked_at": CHECKED_AT.isoformat(),
            },
            "years": years,
        }

    index = {
        "schema_version": 1,
        "generated_at": CHECKED_AT.isoformat(),
        "provisional_through": f"{THROUGH_YEAR}-12-31",
        "markets": index_markets,
    }
    _write_or_check(root / "index.json", _render(index), check=check)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    build(args.root, check=args.check)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
