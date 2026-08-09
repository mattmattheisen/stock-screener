"""Pure reporting for checked-in Market calendar coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..domain.markets.calendar_coverage import (
    MINIMUM_PROVISIONAL_THROUGH,
    CalendarCoverageRegistry,
)


@dataclass(frozen=True, slots=True)
class CalendarCoverageAuditRow:
    market: str
    mic: str
    verified_through: date
    days_remaining: int
    status: str
    source_name: str
    source_url: str


@dataclass(frozen=True, slots=True)
class CalendarCoverageAudit:
    as_of: date
    provisional_through: date
    rows: tuple[CalendarCoverageAuditRow, ...]
    warnings: tuple[str, ...]


def _status(days_remaining: int) -> str:
    if days_remaining < 0:
        return "expired"
    for threshold in (30, 60, 90, 180):
        if days_remaining <= threshold:
            return f"expires-within-{threshold}-days"
    return "ok"


def audit_calendar_coverage(
    registry: CalendarCoverageRegistry,
    *,
    as_of: date,
) -> CalendarCoverageAudit:
    rows = tuple(
        CalendarCoverageAuditRow(
            market=coverage.market,
            mic=coverage.mic,
            verified_through=coverage.verified_through,
            days_remaining=(coverage.verified_through - as_of).days,
            status=_status((coverage.verified_through - as_of).days),
            source_name=coverage.source.name,
            source_url=coverage.source.url,
        )
        for coverage in registry.coverages()
    )
    warnings = [
        (
            f"{row.market} ({row.mic}) calendar {row.status}; verified through "
            f"{row.verified_through.isoformat()} ({row.days_remaining} days); "
            f"source: {row.source_url}"
        )
        for row in rows
        if row.status != "ok"
    ]
    if registry.provisional_through < MINIMUM_PROVISIONAL_THROUGH:
        warnings.append(
            "Provisional calendar horizon ends at "
            f"{registry.provisional_through.isoformat()}; expected at least "
            f"{MINIMUM_PROVISIONAL_THROUGH.isoformat()}"
        )
    return CalendarCoverageAudit(
        as_of=as_of,
        provisional_through=registry.provisional_through,
        rows=rows,
        warnings=tuple(warnings),
    )


def markdown_summary(audit: CalendarCoverageAudit) -> str:
    lines = [
        "## Market calendar coverage",
        "",
        f"Audit date: {audit.as_of.isoformat()}",
        "",
        "| Market | MIC | Verified through | Days remaining | Status | Source |",
        "|---|---|---:|---:|---|---|",
    ]
    lines.extend(
        "| {market} | {mic} | {verified} | {remaining} | {status} | "
        "[{source}]({url}) |".format(
            market=row.market,
            mic=row.mic,
            verified=row.verified_through.isoformat(),
            remaining=row.days_remaining,
            status=row.status,
            source=row.source_name.replace("|", "\\|"),
            url=row.source_url,
        )
        for row in audit.rows
    )
    if audit.warnings:
        lines.extend(("", "### Warnings", ""))
        lines.extend(f"- {warning}" for warning in audit.warnings)
    return "\n".join(lines) + "\n"


def _escape_annotation(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def github_actions_output(audit: CalendarCoverageAudit) -> str:
    annotations = "\n".join(
        f"::warning::{_escape_annotation(warning)}" for warning in audit.warnings
    )
    summary = markdown_summary(audit)
    return f"{annotations}\n{summary}" if annotations else summary
