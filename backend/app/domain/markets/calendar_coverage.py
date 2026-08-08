"""Checked-in official and provisional Market calendar coverage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time
import json
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from .catalog import MarketCatalog, get_market_catalog


MINIMUM_PROVISIONAL_THROUGH = date(2030, 12, 31)


class CalendarManifestError(ValueError):
    """Raised when checked-in calendar data violates its invariants."""


@dataclass(frozen=True, slots=True)
class CalendarSource:
    name: str
    url: str
    checked_at: date


@dataclass(frozen=True, slots=True)
class AnnualCalendarManifest:
    market: str
    mic: str
    year: int
    status: Literal["official", "provisional"]
    sessions: tuple[date, ...]
    close_exceptions: Mapping[date, time]
    source: CalendarSource
    provider: str | None = None
    provider_version: str | None = None


@dataclass(frozen=True, slots=True)
class MarketCalendarCoverage:
    market: str
    mic: str
    verified_through: date
    source: CalendarSource
    annual: Mapping[int, AnnualCalendarManifest]


class CalendarCoverageRegistry:
    """Validated immutable view of repository-owned Market calendars."""

    def __init__(
        self,
        coverage_by_market: Mapping[str, MarketCalendarCoverage],
        *,
        provisional_through: date,
        generated_at: date,
    ) -> None:
        self._coverage_by_market = MappingProxyType(dict(coverage_by_market))
        self.provisional_through = provisional_through
        self.generated_at = generated_at

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        index_name: str = "index.json",
        market_catalog: MarketCatalog | None = None,
    ) -> "CalendarCoverageRegistry":
        root_path = Path(root)
        index = _read_json(root_path / index_name)
        if index.get("schema_version") != 1:
            raise CalendarManifestError("calendar index schema_version must be 1")
        generated_at = _parse_date(index.get("generated_at"), "generated_at")
        provisional_through = _parse_date(
            index.get("provisional_through"), "provisional_through"
        )
        if provisional_through < MINIMUM_PROVISIONAL_THROUGH:
            raise CalendarManifestError(
                "calendar provisional coverage must reach 2030-12-31"
            )

        raw_markets = index.get("markets")
        if not isinstance(raw_markets, dict):
            raise CalendarManifestError("calendar index markets must be an object")
        catalog = market_catalog or get_market_catalog()
        expected_markets = set(catalog.supported_market_codes())
        actual_markets = set(raw_markets)
        if actual_markets != expected_markets:
            missing = sorted(expected_markets - actual_markets)
            extra = sorted(actual_markets - expected_markets)
            raise CalendarManifestError(
                "calendar index must contain exactly the supported Markets "
                f"(missing={missing}, extra={extra})"
            )
        coverage_by_market = {
            market: _load_market_coverage(
                root_path,
                market=market,
                payload=raw_markets[market],
                catalog=catalog,
                provisional_through=provisional_through,
            )
            for market in catalog.supported_market_codes()
        }
        return cls(
            coverage_by_market,
            provisional_through=provisional_through,
            generated_at=generated_at,
        )

    def coverage_for(
        self, market: str, *, mic: str | None = None
    ) -> MarketCalendarCoverage:
        normalized = str(market or "").strip().upper()
        try:
            coverage = self._coverage_by_market[normalized]
        except KeyError as exc:
            raise CalendarManifestError(
                f"calendar coverage is unavailable for Market {market!r}"
            ) from exc
        if mic is not None and str(mic).strip().upper() != coverage.mic:
            raise CalendarManifestError(
                f"calendar coverage for {normalized} is keyed by {coverage.mic}, "
                f"not {mic}"
            )
        return coverage

    def official_sessions(
        self,
        market: str,
        start: date,
        end: date,
        *,
        mic: str | None = None,
    ) -> tuple[date, ...]:
        coverage = self.coverage_for(market, mic=mic)
        return tuple(
            session
            for annual in coverage.annual.values()
            if annual.status == "official"
            for session in annual.sessions
            if start <= session <= end
        )


def _load_market_coverage(
    root: Path,
    *,
    market: str,
    payload: object,
    catalog: MarketCatalog,
    provisional_through: date,
) -> MarketCalendarCoverage:
    if not isinstance(payload, dict):
        raise CalendarManifestError(f"{market} calendar entry must be an object")
    catalog_entry = catalog.get(market)
    mic = _required_text(payload.get("mic"), f"{market}.mic").upper()
    if mic != catalog_entry.primary_mic:
        raise CalendarManifestError(
            f"{market} calendar MIC {mic} does not match primary MIC "
            f"{catalog_entry.primary_mic}"
        )
    verified_through = _parse_date(
        payload.get("verified_through"), f"{market}.verified_through"
    )
    source = _parse_source(payload.get("source"), f"{market}.source")
    raw_years = payload.get("years")
    if not isinstance(raw_years, dict) or not raw_years:
        raise CalendarManifestError(f"{market}.years must be a non-empty object")

    annual_by_year: dict[int, AnnualCalendarManifest] = {}
    for raw_year, raw_relative_path in raw_years.items():
        try:
            year = int(raw_year)
        except (TypeError, ValueError) as exc:
            raise CalendarManifestError(
                f"{market}.years key {raw_year!r} is not a year"
            ) from exc
        relative_path = Path(
            _required_text(raw_relative_path, f"{market}.years.{raw_year}")
        )
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise CalendarManifestError(
                f"{market}.years.{raw_year} must stay within the calendar root"
            )
        annual_by_year[year] = _parse_annual_manifest(
            _read_json(root / relative_path),
            expected_market=market,
            expected_mic=mic,
            expected_year=year,
        )

    official_years = sorted(
        year
        for year, annual in annual_by_year.items()
        if annual.status == "official"
    )
    if not official_years:
        raise CalendarManifestError(f"{market} has no official calendar year")
    if verified_through.year > official_years[-1]:
        raise CalendarManifestError(
            f"{market}.verified_through exceeds its last official year"
        )
    if provisional_through.year not in annual_by_year:
        raise CalendarManifestError(
            f"{market} has no annual manifest through {provisional_through.year}"
        )
    if annual_by_year[provisional_through.year].status != "provisional":
        raise CalendarManifestError(
            f"{market} {provisional_through.year} must remain provisional"
        )

    return MarketCalendarCoverage(
        market=market,
        mic=mic,
        verified_through=verified_through,
        source=source,
        annual=MappingProxyType(dict(sorted(annual_by_year.items()))),
    )


def _parse_annual_manifest(
    payload: object,
    *,
    expected_market: str,
    expected_mic: str,
    expected_year: int,
) -> AnnualCalendarManifest:
    if not isinstance(payload, dict):
        raise CalendarManifestError(
            f"{expected_market} {expected_year} manifest must be an object"
        )
    market = _required_text(payload.get("market"), "annual.market").upper()
    mic = _required_text(payload.get("mic"), "annual.mic").upper()
    year = payload.get("year")
    status = payload.get("status")
    if market != expected_market or mic != expected_mic or year != expected_year:
        raise CalendarManifestError(
            f"{expected_market} {expected_year} annual Market/MIC/year metadata mismatch"
        )
    if status not in {"official", "provisional"}:
        raise CalendarManifestError(
            f"{expected_market} {expected_year} status must be official or provisional"
        )
    source = _parse_source(payload.get("source"), "annual.source")
    raw_sessions = payload.get("sessions")
    if not isinstance(raw_sessions, list):
        raise CalendarManifestError("annual.sessions must be an array")
    sessions = tuple(
        _parse_date(raw_session, "annual.sessions")
        for raw_session in raw_sessions
    )
    if len(set(sessions)) != len(sessions):
        raise CalendarManifestError("annual.sessions contains a duplicate session")
    if sessions != tuple(sorted(sessions)):
        raise CalendarManifestError("annual.sessions must be sorted")
    if any(session.year != expected_year for session in sessions):
        raise CalendarManifestError(
            "annual.sessions must stay within the declared year"
        )

    raw_close_exceptions = payload.get("close_exceptions", {})
    if not isinstance(raw_close_exceptions, dict):
        raise CalendarManifestError("annual.close_exceptions must be an object")
    close_exceptions: dict[date, time] = {}
    for raw_day, raw_close in raw_close_exceptions.items():
        close_day = _parse_date(raw_day, "annual.close_exceptions date")
        if close_day not in sessions:
            raise CalendarManifestError(
                f"close exception {close_day.isoformat()} is not a declared session"
            )
        try:
            close_exceptions[close_day] = time.fromisoformat(
                _required_text(raw_close, "annual.close_exceptions time")
            )
        except ValueError as exc:
            raise CalendarManifestError(
                f"invalid close exception time {raw_close!r}"
            ) from exc

    provider = payload.get("provider")
    provider_version = payload.get("provider_version")
    if status == "provisional":
        provider = _required_text(provider, "annual.provider")
        provider_version = _required_text(
            provider_version, "annual.provider_version"
        )
    elif provider is not None or provider_version is not None:
        raise CalendarManifestError(
            "official annual manifests must not claim provider generation"
        )

    return AnnualCalendarManifest(
        market=market,
        mic=mic,
        year=expected_year,
        status=status,
        sessions=sessions,
        close_exceptions=MappingProxyType(close_exceptions),
        source=source,
        provider=provider,
        provider_version=provider_version,
    )


def _parse_source(payload: object, field: str) -> CalendarSource:
    if not isinstance(payload, dict):
        raise CalendarManifestError(f"{field} must be an object")
    return CalendarSource(
        name=_required_text(payload.get("name"), f"{field}.name"),
        url=_required_text(payload.get("url"), f"{field}.url"),
        checked_at=_parse_date(payload.get("checked_at"), f"{field}.checked_at"),
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CalendarManifestError(f"{field} must be a non-empty string")
    return value.strip()


def _parse_date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(_required_text(value, field))
    except ValueError as exc:
        raise CalendarManifestError(f"{field} must be an ISO date") from exc


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CalendarManifestError(
            f"unable to read calendar manifest {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CalendarManifestError(
            f"invalid JSON in calendar manifest {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise CalendarManifestError(f"calendar manifest {path} must be an object")
    return payload


__all__ = [
    "AnnualCalendarManifest",
    "CalendarCoverageRegistry",
    "CalendarManifestError",
    "CalendarSource",
    "MarketCalendarCoverage",
]
