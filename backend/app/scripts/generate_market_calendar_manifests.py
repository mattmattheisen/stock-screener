"""Generate provisional or import normalized official calendar manifests."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from app.domain.markets.calendar_coverage import CalendarSource
from app.domain.markets.catalog import get_market_catalog
from app.services.calendar_manifest_generation import CalendarManifestGenerator


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "market_calendars"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--market", action="append")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--through-year", type=int, default=2030)
    parser.add_argument(
        "--status", choices=("provisional", "official"), default="provisional"
    )
    parser.add_argument("--year", type=int)
    parser.add_argument("--official-sessions", type=Path)
    parser.add_argument("--source-name")
    parser.add_argument("--source-url")
    parser.add_argument("--checked-at", type=date.fromisoformat, default=date.today())
    parser.add_argument("--check", action="store_true")
    return parser


def _official_sessions(path: Path) -> tuple[date, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("--official-sessions must contain a JSON date array")
    return tuple(date.fromisoformat(str(value)) for value in payload)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalog = get_market_catalog()
    markets = args.market or catalog.supported_market_codes()
    generator = CalendarManifestGenerator(market_catalog=catalog)
    for market in markets:
        if args.status == "official":
            if not all(
                (
                    args.year,
                    args.official_sessions,
                    args.source_name,
                    args.source_url,
                )
            ):
                raise SystemExit(
                    "official import requires --year, --official-sessions, "
                    "--source-name, and --source-url"
                )
            generator.import_official_year(
                args.root,
                market=market,
                year=args.year,
                sessions=_official_sessions(args.official_sessions),
                source=CalendarSource(
                    name=args.source_name,
                    url=args.source_url,
                    checked_at=args.checked_at,
                ),
                check=args.check,
            )
            continue

        provider = catalog.get(market).primary_mic_facts.calendar_provider
        generator.generate_provisional_years(
            args.root,
            market=market,
            start_year=args.start_year or date.today().year + 1,
            through_year=args.through_year,
            source=CalendarSource(
                name=f"Pinned {provider.value} generated schedule",
                url=(
                    "https://github.com/gerrymanoim/exchange_calendars"
                    if provider.value == "exchange_calendars"
                    else "https://github.com/rsheftel/pandas_market_calendars"
                ),
                checked_at=args.checked_at,
            ),
            check=args.check,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
