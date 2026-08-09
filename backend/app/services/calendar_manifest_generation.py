"""Deterministic generation of checked-in annual calendar manifests."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, time, timedelta
from importlib import metadata
import json
from pathlib import Path

import pandas as pd

from app.domain.markets.calendar_coverage import CalendarSource
from app.domain.markets.calendar_policy import CalendarProvider
from app.domain.markets.catalog import MarketCatalog, get_market_catalog

try:
    import exchange_calendars as xcals  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - runtime dependency guard
    xcals = None  # type: ignore

try:
    import pandas_market_calendars as pmc  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - runtime dependency guard
    pmc = None  # type: ignore


class CalendarManifestGenerationError(RuntimeError):
    """Raised when annual manifest generation cannot be completed safely."""


class CalendarManifestGenerator:
    def __init__(
        self,
        *,
        market_catalog: MarketCatalog | None = None,
        calendar_providers: Mapping[CalendarProvider, Callable[[str], object]]
        | None = None,
        provider_versions: Mapping[CalendarProvider, str] | None = None,
    ) -> None:
        self._market_catalog = market_catalog or get_market_catalog()
        self._calendar_providers = dict(calendar_providers or {})
        self._provider_versions = dict(provider_versions or {})

    def generate_provisional_years(
        self,
        root: str | Path,
        *,
        market: str,
        start_year: int,
        through_year: int,
        source: CalendarSource,
        check: bool = False,
    ) -> tuple[Path, ...]:
        if start_year > through_year:
            raise CalendarManifestGenerationError(
                "start_year must not be after through_year"
            )
        entry = self._market_catalog.get(market)
        market_dir = Path(root) / entry.code.lower()
        planned: list[tuple[Path, str]] = []
        for year in range(start_year, through_year + 1):
            official_path = market_dir / f"{year}.json"
            if official_path.exists():
                raise CalendarManifestGenerationError(
                    f"refusing to overwrite official calendar {official_path}"
                )
            sessions, provider, provider_version = self._provider_sessions(
                entry.code, year
            )
            payload = _annual_payload(
                market=entry.code,
                mic=entry.primary_mic,
                year=year,
                status="provisional",
                sessions=sessions,
                source=source,
                provider=provider.value,
                provider_version=provider_version,
            )
            path = market_dir / f"{year}.provisional.json"
            planned.append((path, _render_json(payload)))

        self._write_or_check(planned, check=check)
        return tuple(path for path, _content in planned)

    def import_official_year(
        self,
        root: str | Path,
        *,
        market: str,
        year: int,
        sessions: Iterable[date],
        source: CalendarSource,
        close_exceptions: Mapping[date, time] | None = None,
        check: bool = False,
    ) -> Path:
        entry = self._market_catalog.get(market)
        payload = _annual_payload(
            market=entry.code,
            mic=entry.primary_mic,
            year=year,
            status="official",
            sessions=sessions,
            source=source,
            close_exceptions=close_exceptions,
        )
        path = Path(root) / entry.code.lower() / f"{year}.json"
        self._write_or_check(((path, _render_json(payload)),), check=check)
        return path

    def import_provisional_year(
        self,
        root: str | Path,
        *,
        market: str,
        year: int,
        sessions: Iterable[date],
        source: CalendarSource,
        provider: str,
        provider_version: str,
        check: bool = False,
    ) -> Path:
        entry = self._market_catalog.get(market)
        official_path = Path(root) / entry.code.lower() / f"{year}.json"
        if official_path.exists():
            raise CalendarManifestGenerationError(
                f"refusing to overwrite official calendar {official_path}"
            )
        payload = _annual_payload(
            market=entry.code,
            mic=entry.primary_mic,
            year=year,
            status="provisional",
            sessions=sessions,
            source=source,
            provider=provider,
            provider_version=provider_version,
        )
        path = Path(root) / entry.code.lower() / f"{year}.provisional.json"
        self._write_or_check(((path, _render_json(payload)),), check=check)
        return path

    def import_official_closures(
        self,
        root: str | Path,
        *,
        market: str,
        year: int,
        closures: Iterable[date],
        source: CalendarSource,
        extra_sessions: Iterable[date] = (),
        close_exceptions: Mapping[date, time] | None = None,
        check: bool = False,
    ) -> Path:
        closure_dates = frozenset(closures)
        extra_session_dates = frozenset(extra_sessions)
        if any(day.year != year for day in (*closure_dates, *extra_session_dates)):
            raise CalendarManifestGenerationError(
                f"{market} {year} closures and extra sessions must stay in year"
            )
        sessions: set[date] = set(extra_session_dates)
        candidate = date(year, 1, 1)
        final_day = date(year, 12, 31)
        while candidate <= final_day:
            if candidate.weekday() < 5 and candidate not in closure_dates:
                sessions.add(candidate)
            candidate += timedelta(days=1)
        return self.import_official_year(
            root,
            market=market,
            year=year,
            sessions=sessions,
            source=source,
            close_exceptions=close_exceptions,
            check=check,
        )

    def _provider_sessions(
        self,
        market: str,
        year: int,
    ) -> tuple[tuple[date, ...], CalendarProvider, str]:
        facts = self._market_catalog.get(market).primary_mic_facts
        provider_kind = facts.calendar_provider
        provider_id = facts.provider_calendar_id or facts.calendar_id
        try:
            raw_calendar = self._provider_calendar(
                provider_kind,
                provider_id,
                year=year,
            )
            sessions = tuple(
                sorted(
                    _sessions_in_range(
                        raw_calendar,
                        date(year, 1, 1),
                        date(year, 12, 31),
                    )
                )
            )
        except Exception as exc:
            raise CalendarManifestGenerationError(
                f"{market} {year} provider schedule is unavailable: {exc}"
            ) from exc
        if not sessions:
            raise CalendarManifestGenerationError(
                f"{market} {year} provider schedule contains no sessions"
            )
        return sessions, provider_kind, self._provider_version(provider_kind)

    def _provider_calendar(
        self,
        provider: CalendarProvider,
        calendar_id: str,
        *,
        year: int,
    ) -> object:
        custom = self._calendar_providers.get(provider)
        if custom is not None:
            return custom(calendar_id)
        if provider is CalendarProvider.EXCHANGE_CALENDARS and xcals is not None:
            return xcals.get_calendar(
                calendar_id,
                start=f"{year}-01-01",
                end=f"{year}-12-31",
            )
        if provider is CalendarProvider.PANDAS_MARKET_CALENDARS and pmc is not None:
            return pmc.get_calendar(calendar_id)
        raise CalendarManifestGenerationError(
            f"calendar provider {provider.value} is not installed"
        )

    def _provider_version(self, provider: CalendarProvider) -> str:
        explicit = self._provider_versions.get(provider)
        if explicit:
            return explicit
        try:
            return metadata.version(provider.package_name)
        except metadata.PackageNotFoundError as exc:
            raise CalendarManifestGenerationError(
                f"cannot resolve installed version for {provider.value}"
            ) from exc

    @staticmethod
    def _write_or_check(
        planned: Iterable[tuple[Path, str]],
        *,
        check: bool,
    ) -> None:
        planned_files = tuple(planned)
        if check:
            drifted = [
                path
                for path, content in planned_files
                if not path.exists()
                or path.read_text(encoding="utf-8") != content
            ]
            if drifted:
                raise CalendarManifestGenerationError(
                    "calendar manifest drift detected: "
                    + ", ".join(str(path) for path in drifted)
                )
            return
        for path, content in planned_files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


def _annual_payload(
    *,
    market: str,
    mic: str,
    year: int,
    status: str,
    sessions: Iterable[date],
    source: CalendarSource,
    close_exceptions: Mapping[date, time] | None = None,
    provider: str | None = None,
    provider_version: str | None = None,
) -> dict[str, object]:
    normalized_sessions = tuple(sorted(set(sessions)))
    if not normalized_sessions:
        raise CalendarManifestGenerationError(
            f"{market} {year} calendar contains no sessions"
        )
    if any(session.year != year for session in normalized_sessions):
        raise CalendarManifestGenerationError(
            f"{market} {year} calendar contains a session outside its year"
        )
    normalized_close_exceptions = dict(close_exceptions or {})
    session_dates = frozenset(normalized_sessions)
    for exception_date in normalized_close_exceptions:
        if exception_date not in session_dates:
            raise CalendarManifestGenerationError(
                f"{market} {year} exceptional close must be a session: "
                f"{exception_date.isoformat()}"
            )
    payload: dict[str, object] = {
        "market": market,
        "mic": mic,
        "year": year,
        "status": status,
        "source": {
            "name": source.name,
            "url": source.url,
            "checked_at": source.checked_at.isoformat(),
        },
    }
    if status == "provisional":
        if not provider or not provider_version:
            raise CalendarManifestGenerationError(
                "provisional calendars require provider provenance"
            )
        payload["provider"] = provider
        payload["provider_version"] = provider_version
    if normalized_close_exceptions:
        payload["close_exceptions"] = {
            exception_date.isoformat(): normalized_close_exceptions[
                exception_date
            ].isoformat()
            for exception_date in sorted(normalized_close_exceptions)
        }
    payload["sessions"] = [session.isoformat() for session in normalized_sessions]
    return payload


def _render_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _sessions_in_range(
    raw_calendar: object,
    start_day: date,
    end_day: date,
) -> tuple[date, ...]:
    sessions_in_range = getattr(raw_calendar, "sessions_in_range", None)
    if callable(sessions_in_range):
        first_session = _session_bound(raw_calendar, "first_session")
        last_session = _session_bound(raw_calendar, "last_session")
        effective_start = max(start_day, first_session) if first_session else start_day
        effective_end = min(end_day, last_session) if last_session else end_day
        if effective_start > effective_end:
            return ()
        return tuple(
            pd.Timestamp(session).date()
            for session in sessions_in_range(
                pd.Timestamp(effective_start),
                pd.Timestamp(effective_end),
            )
        )

    sessions = getattr(raw_calendar, "sessions", None)
    if sessions is not None:
        return tuple(
            day
            for day in (pd.Timestamp(session).date() for session in sessions)
            if start_day <= day <= end_day
        )

    schedule = getattr(raw_calendar, "schedule", None)
    if callable(schedule):
        schedule = schedule(
            start_date=pd.Timestamp(start_day),
            end_date=pd.Timestamp(end_day),
        )
    if hasattr(schedule, "index"):
        return tuple(pd.Timestamp(session).date() for session in schedule.index)
    raise CalendarManifestGenerationError(
        "provider calendar does not expose a usable session schedule"
    )


def _session_bound(raw_calendar: object, name: str) -> date | None:
    value = getattr(raw_calendar, name, None)
    if callable(value):
        value = value()
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    return timestamp.date()


__all__ = [
    "CalendarManifestGenerationError",
    "CalendarManifestGenerator",
]
