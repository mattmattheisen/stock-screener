"""Rebuild the checked-in Market calendar data set from reviewed inputs."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path

import pandas_market_calendars as pmc

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

ADDITIONAL_OFFICIAL_CLOSURES = {
    ("JP", 2026): {date(2026, 3, 20), date(2026, 9, 22), date(2026, 9, 23)},
    ("KR", 2026): {date(2026, 5, 25), date(2026, 6, 3), date(2026, 7, 17)},
    ("TW", 2026): {
        date(2026, 1, 1),
        date(2026, 2, 12),
        date(2026, 2, 13),
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 2, 19),
        date(2026, 2, 20),
        date(2026, 2, 27),
        date(2026, 4, 3),
        date(2026, 4, 6),
        date(2026, 5, 1),
        date(2026, 6, 19),
        date(2026, 9, 25),
        date(2026, 9, 28),
        date(2026, 10, 9),
        date(2026, 10, 26),
        date(2026, 12, 25),
    },
    ("MY", 2026): {
        date(2026, 3, 23),
        date(2026, 6, 1),
        date(2026, 6, 17),
    },
}

OFFICIAL_WEEKDAY_CLOSURES = {
    ("CN", 2026): {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 2, 19),
        date(2026, 2, 20),
        date(2026, 2, 23),
        date(2026, 4, 6),
        date(2026, 5, 1),
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 6, 19),
        date(2026, 9, 25),
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 5),
        date(2026, 10, 6),
        date(2026, 10, 7),
    },
    ("SG", 2026): {
        date(2026, 1, 1),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 4, 3),
        date(2026, 5, 1),
        date(2026, 5, 27),
        date(2026, 6, 1),
        date(2026, 8, 10),
        date(2026, 11, 9),
        date(2026, 12, 25),
    },
}


def _weekdays(year: int) -> tuple[date, ...]:
    sessions = []
    candidate = date(year, 1, 1)
    while candidate <= date(year, 12, 31):
        if candidate.weekday() < 5:
            sessions.append(candidate)
        candidate += timedelta(days=1)
    return tuple(sessions)


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
                if (market, year) in OFFICIAL_WEEKDAY_CLOSURES:
                    output = generator.import_official_closures(
                        root,
                        market=market,
                        year=year,
                        closures=OFFICIAL_WEEKDAY_CLOSURES[(market, year)],
                        source=_source(market),
                        check=check,
                    )
                else:
                    sessions, _provider, _version = generator._provider_sessions(  # noqa: SLF001 - deterministic data builder
                        market, year
                    )
                    sessions = tuple(
                        session
                        for session in sessions
                        if session
                        not in ADDITIONAL_OFFICIAL_CLOSURES.get((market, year), set())
                    )
                    output = generator.import_official_year(
                        root,
                        market=market,
                        year=year,
                        sessions=sessions,
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
                    sessions=_weekdays(year),
                    source=CalendarSource(
                        name="Project rule-generated Singapore planning calendar",
                        url="https://www.sgx.com/stock-exchange/clearing-information",
                        checked_at=CHECKED_AT,
                    ),
                    provider="project_weekday_rules",
                    provider_version="1",
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
