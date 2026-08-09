"""Validated declarative inputs for official Market calendar generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from .calendar_coverage import CalendarSource


class _MarketCatalog(Protocol):
    def supported_market_codes(self) -> tuple[str, ...]:
        ...


class ReviewedCalendarInputError(ValueError):
    """Raised when reviewed calendar facts violate their schema."""


@dataclass(frozen=True, slots=True)
class ReviewedMarketCalendar:
    source: CalendarSource
    official_through: int
    closures: Mapping[int, frozenset[date]]


@dataclass(frozen=True, slots=True)
class ReviewedCalendarInput:
    checked_at: date
    markets: Mapping[str, ReviewedMarketCalendar]

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        market_catalog: _MarketCatalog,
        first_year: int,
    ) -> "ReviewedCalendarInput":
        payload = _read_json(Path(path))
        if payload.get("schema_version") != 1:
            raise ReviewedCalendarInputError(
                "reviewed calendar schema_version must be 1"
            )
        checked_at = _parse_date(payload.get("checked_at"), "checked_at")
        raw_markets = payload.get("markets")
        if not isinstance(raw_markets, dict):
            raise ReviewedCalendarInputError("markets must be an object")

        expected = set(market_catalog.supported_market_codes())
        actual = set(raw_markets)
        if actual != expected:
            raise ReviewedCalendarInputError(
                "reviewed calendars must contain exactly supported Markets "
                f"(missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)})"
            )
        markets = {
            market: _parse_market(
                market,
                raw_markets[market],
                checked_at=checked_at,
                first_year=first_year,
            )
            for market in sorted(expected)
        }
        return cls(
            checked_at=checked_at,
            markets=MappingProxyType(markets),
        )

    def source_for(self, market: str) -> CalendarSource:
        return self._market(market).source

    def closures_for(self, market: str, year: int) -> frozenset[date]:
        try:
            return self._market(market).closures[year]
        except KeyError as exc:
            raise ReviewedCalendarInputError(
                f"{market.upper()} missing closures for {year}"
            ) from exc

    def official_through(self, market: str) -> int:
        return self._market(market).official_through

    def _market(self, market: str) -> ReviewedMarketCalendar:
        normalized = str(market or "").strip().upper()
        try:
            return self.markets[normalized]
        except KeyError as exc:
            raise ReviewedCalendarInputError(
                f"unsupported reviewed calendar Market: {normalized}"
            ) from exc


def _parse_market(
    market: str,
    payload: object,
    *,
    checked_at: date,
    first_year: int,
) -> ReviewedMarketCalendar:
    if not isinstance(payload, dict):
        raise ReviewedCalendarInputError(f"{market} must be an object")
    raw_source = payload.get("source")
    if not isinstance(raw_source, dict):
        raise ReviewedCalendarInputError(f"{market}.source must be an object")
    source = CalendarSource(
        name=_required_text(raw_source.get("name"), f"{market}.source.name"),
        url=_required_text(raw_source.get("url"), f"{market}.source.url"),
        checked_at=checked_at,
    )
    official_through = payload.get("official_through")
    if not isinstance(official_through, int) or official_through < first_year:
        raise ReviewedCalendarInputError(
            f"{market}.official_through must be at least {first_year}"
        )
    raw_closures = payload.get("closures")
    if not isinstance(raw_closures, dict):
        raise ReviewedCalendarInputError(f"{market}.closures must be an object")

    expected_years = set(range(first_year, official_through + 1))
    try:
        actual_years = {int(raw_year) for raw_year in raw_closures}
    except (TypeError, ValueError) as exc:
        raise ReviewedCalendarInputError(
            f"{market}.closures keys must be years"
        ) from exc
    missing_years = sorted(expected_years - actual_years)
    extra_years = sorted(actual_years - expected_years)
    if missing_years:
        raise ReviewedCalendarInputError(
            f"{market} missing closures for {missing_years[0]}"
        )
    if extra_years:
        raise ReviewedCalendarInputError(
            f"{market} has closures outside official coverage: {extra_years}"
        )

    closures: dict[int, frozenset[date]] = {}
    for year in sorted(expected_years):
        raw_dates = raw_closures[str(year)]
        if not isinstance(raw_dates, list):
            raise ReviewedCalendarInputError(
                f"{market}.closures.{year} must be an array"
            )
        parsed_dates = tuple(
            _parse_date(raw_date, f"{market}.closures.{year}")
            for raw_date in raw_dates
        )
        if len(parsed_dates) != len(set(parsed_dates)):
            raise ReviewedCalendarInputError(
                f"{market}.closures.{year} contains duplicate dates"
            )
        outside = [closure for closure in parsed_dates if closure.year != year]
        if outside:
            raise ReviewedCalendarInputError(
                f"{market} closure {outside[0].isoformat()} is outside {year}"
            )
        closures[year] = frozenset(parsed_dates)
    return ReviewedMarketCalendar(
        source=source,
        official_through=official_through,
        closures=MappingProxyType(closures),
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewedCalendarInputError(f"{field} must be non-empty text")
    return value.strip()


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ReviewedCalendarInputError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ReviewedCalendarInputError(f"{field} must be an ISO date") from exc


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewedCalendarInputError(
            f"cannot read reviewed calendar input {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ReviewedCalendarInputError("reviewed calendar root must be an object")
    return payload
