"""Backfill frozen breadth contributor snapshots from cached price history."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence

from app.database import SessionLocal
from app.domain.markets.catalog import get_market_catalog
from app.services.breadth_calculator_service import BreadthCalculatorService
from app.services.breadth_contributor_backfill import (
    BreadthContributorBackfillService,
)
from app.wiring.bootstrap import get_price_cache


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--markets",
        help="Comma-separated breadth-enabled market codes; defaults to all",
    )
    parser.add_argument("--limit", type=int, default=20)
    return parser


def _default_run_market(market: str, limit: int) -> dict[str, int | str]:
    with SessionLocal() as db:
        calculator = BreadthCalculatorService(
            db,
            get_price_cache(),
            market=market,
        )
        return BreadthContributorBackfillService(
            db,
            calculator=calculator,
        ).run(limit=limit)


def main(
    argv: Sequence[str] | None = None,
    *,
    run_market: Callable[[str, int], dict[str, int | str]] = _default_run_market,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")

    catalog = get_market_catalog()
    breadth_markets = set(catalog.market_codes_with_capability("breadth"))
    if args.markets is not None:
        markets = tuple(
            dict.fromkeys(
                item.strip().upper()
                for item in args.markets.split(",")
                if item.strip()
            )
        )
        if not markets:
            parser.error("--markets must include at least one market code")
    else:
        markets = tuple(catalog.market_codes_with_capability("breadth"))
    invalid = sorted(set(markets) - breadth_markets)
    if invalid:
        parser.error(
            "markets are not breadth-enabled: " + ", ".join(invalid)
        )

    reports: list[dict[str, object]] = []
    failed = False
    for market in markets:
        try:
            report = dict(run_market(market, args.limit))
            reports.append(report)
            if int(report.get("skipped_unverifiable_dates", 0)) > 0:
                failed = True
        except Exception as exc:
            failed = True
            reports.append({"market": market, "error": str(exc)})
    print(json.dumps(reports, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
