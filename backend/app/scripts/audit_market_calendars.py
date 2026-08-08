"""Report official Market calendar expiry without failing on warning states."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import os
from pathlib import Path
import sys

from ..domain.markets.calendar_coverage import (
    CalendarCoverageRegistry,
    CalendarManifestError,
)
from ..services.calendar_coverage_audit import (
    audit_calendar_coverage,
    github_actions_output,
    markdown_summary,
)


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data/market_calendars"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--github-actions", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    as_of = args.as_of or datetime.now(timezone.utc).date()
    try:
        registry = CalendarCoverageRegistry.load(args.root)
    except (CalendarManifestError, OSError, ValueError) as exc:
        print(f"Market calendar manifest validation failed: {exc}", file=sys.stderr)
        return 2
    audit = audit_calendar_coverage(registry, as_of=as_of)
    summary = markdown_summary(audit)
    if args.github_actions:
        print(github_actions_output(audit), end="")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as handle:
                handle.write(summary)
    else:
        print(summary, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
