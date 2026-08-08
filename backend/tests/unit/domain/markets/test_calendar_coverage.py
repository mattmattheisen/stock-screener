from __future__ import annotations

from datetime import date, time
import json
from pathlib import Path
import shutil

import pytest

from app.domain.markets.calendar_coverage import (
    CalendarCoverageRegistry,
    CalendarManifestError,
)
from app.domain.markets.catalog import MarketCatalog, get_market_catalog


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "fixtures" / "market_calendars"
)


def _kr_catalog() -> MarketCatalog:
    return MarketCatalog((get_market_catalog().get("KR"),))


def _copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "market_calendars"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def _mutate_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_registry_loads_official_sessions_and_close_exceptions() -> None:
    registry = CalendarCoverageRegistry.load(
        FIXTURE_ROOT,
        index_name="minimal-index.json",
        market_catalog=_kr_catalog(),
    )

    coverage = registry.coverage_for("kr")

    assert coverage.market == "KR"
    assert coverage.mic == "XKRX"
    assert coverage.verified_through == date(2026, 12, 31)
    assert registry.official_sessions(
        "KR", date(2026, 1, 1), date(2026, 12, 31)
    ) == (date(2026, 1, 2), date(2026, 12, 30))
    assert coverage.annual[2026].close_exceptions == {
        date(2026, 12, 30): time(15, 0)
    }
    assert coverage.annual[2030].status == "provisional"


def test_registry_rejects_verified_through_after_last_official_year(
    tmp_path: Path,
) -> None:
    root = _copy_fixture(tmp_path)
    _mutate_json(
        root / "minimal-index.json",
        lambda payload: payload["markets"]["KR"].update(
            {"verified_through": "2027-12-31"}
        ),
    )

    with pytest.raises(CalendarManifestError, match="verified_through"):
        CalendarCoverageRegistry.load(
            root,
            index_name="minimal-index.json",
            market_catalog=_kr_catalog(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload.update(
                {"sessions": ["2026-12-30", "2026-01-02"]}
            ),
            "sorted",
        ),
        (
            lambda payload: payload.update(
                {"sessions": ["2026-01-02", "2026-01-02"]}
            ),
            "duplicate",
        ),
        (
            lambda payload: payload.update({"sessions": ["2027-01-04"]}),
            "declared year",
        ),
    ],
)
def test_registry_rejects_invalid_session_sequences(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    root = _copy_fixture(tmp_path)
    _mutate_json(root / "kr" / "2026.json", mutation)

    with pytest.raises(CalendarManifestError, match=message):
        CalendarCoverageRegistry.load(
            root,
            index_name="minimal-index.json",
            market_catalog=_kr_catalog(),
        )


def test_registry_rejects_missing_source_provenance(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    _mutate_json(
        root / "kr" / "2026.json",
        lambda payload: payload["source"].update({"url": ""}),
    )

    with pytest.raises(CalendarManifestError, match="source.url"):
        CalendarCoverageRegistry.load(
            root,
            index_name="minimal-index.json",
            market_catalog=_kr_catalog(),
        )


def test_registry_rejects_close_exception_for_non_session(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    _mutate_json(
        root / "kr" / "2026.json",
        lambda payload: payload.update(
            {"close_exceptions": {"2026-05-25": "15:00:00"}}
        ),
    )

    with pytest.raises(CalendarManifestError, match="close exception"):
        CalendarCoverageRegistry.load(
            root,
            index_name="minimal-index.json",
            market_catalog=_kr_catalog(),
        )


def test_registry_rejects_missing_catalog_market(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)

    with pytest.raises(CalendarManifestError, match="supported Markets"):
        CalendarCoverageRegistry.load(
            root,
            index_name="minimal-index.json",
            market_catalog=get_market_catalog(),
        )


def test_registry_rejects_provisional_horizon_before_2030(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    _mutate_json(
        root / "minimal-index.json",
        lambda payload: payload.update(
            {"provisional_through": "2029-12-31"}
        ),
    )

    with pytest.raises(CalendarManifestError, match="2030-12-31"):
        CalendarCoverageRegistry.load(
            root,
            index_name="minimal-index.json",
            market_catalog=_kr_catalog(),
        )


def test_registry_accepts_official_coverage_replacing_provisional_horizon(
    tmp_path: Path,
) -> None:
    root = _copy_fixture(tmp_path)
    for year in range(2027, 2031):
        path = root / "kr" / f"{year}.provisional.json"

        def promote(payload):
            payload["status"] = "official"
            payload.pop("provider")
            payload.pop("provider_version")

        _mutate_json(path, promote)
    _mutate_json(
        root / "minimal-index.json",
        lambda payload: payload["markets"]["KR"].update(
            {"verified_through": "2030-12-31"}
        ),
    )

    registry = CalendarCoverageRegistry.load(
        root,
        index_name="minimal-index.json",
        market_catalog=_kr_catalog(),
    )

    assert registry.coverage_for("KR").annual[2030].status == "official"
