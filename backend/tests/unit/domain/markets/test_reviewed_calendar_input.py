from __future__ import annotations

from datetime import date, time
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.markets.catalog import get_market_catalog
from app.domain.markets.reviewed_calendar_input import (
    ReviewedCalendarInput,
    ReviewedCalendarInputError,
)


PRODUCTION_INPUT = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "market_calendars"
    / "inputs"
    / "reviewed_official_calendars.json"
)


def _catalog(*markets):
    return SimpleNamespace(supported_market_codes=lambda: tuple(markets))


def _payload(*, markets=None):
    return {
        "schema_version": 1,
        "checked_at": "2026-08-08",
        "markets": markets
        or {
            "US": {
                "source": {"name": "NYSE calendar", "url": "https://nyse.test"},
                "official_through": 2026,
                "closures": {"2026": ["2026-01-01"]},
                "close_exceptions": {
                    "2026": {"2026-11-27": "13:00:00"}
                },
            }
        },
    }


def _write(tmp_path, payload):
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_typed_reviewed_calendar_facts(tmp_path):
    reviewed = ReviewedCalendarInput.load(
        _write(tmp_path, _payload()),
        market_catalog=_catalog("US"),
        first_year=2026,
    )

    assert reviewed.checked_at == date(2026, 8, 8)
    assert reviewed.official_through("US") == 2026
    assert reviewed.closures_for("US", 2026) == frozenset({date(2026, 1, 1)})
    assert reviewed.close_exceptions_for("US", 2026) == {
        date(2026, 11, 27): time(13, 0)
    }
    assert reviewed.source_for("US").url == "https://nyse.test"


def test_omitted_close_exceptions_are_an_empty_immutable_mapping(tmp_path):
    payload = _payload()
    del payload["markets"]["US"]["close_exceptions"]
    reviewed = ReviewedCalendarInput.load(
        _write(tmp_path, payload),
        market_catalog=_catalog("US"),
        first_year=2026,
    )

    exceptions = reviewed.close_exceptions_for("US", 2026)

    assert exceptions == {}
    with pytest.raises(TypeError):
        exceptions[date(2026, 11, 27)] = time(13, 0)


def test_rejects_missing_supported_market(tmp_path):
    with pytest.raises(ReviewedCalendarInputError, match="missing=.*HK"):
        ReviewedCalendarInput.load(
            _write(tmp_path, _payload()),
            market_catalog=_catalog("US", "HK"),
            first_year=2026,
        )


def test_rejects_missing_official_year(tmp_path):
    payload = _payload()
    payload["markets"]["US"]["official_through"] = 2027

    with pytest.raises(ReviewedCalendarInputError, match="missing closures for 2027"):
        ReviewedCalendarInput.load(
            _write(tmp_path, payload),
            market_catalog=_catalog("US"),
            first_year=2026,
        )


def test_rejects_closure_outside_declared_year(tmp_path):
    payload = _payload()
    payload["markets"]["US"]["closures"]["2026"] = ["2027-01-01"]

    with pytest.raises(ReviewedCalendarInputError, match="outside 2026"):
        ReviewedCalendarInput.load(
            _write(tmp_path, payload),
            market_catalog=_catalog("US"),
            first_year=2026,
        )


def test_rejects_exceptional_close_with_invalid_time(tmp_path):
    payload = _payload()
    payload["markets"]["US"]["close_exceptions"]["2026"] = {
        "2026-11-27": "25:00:00"
    }

    with pytest.raises(ReviewedCalendarInputError, match="must be an ISO time"):
        ReviewedCalendarInput.load(
            _write(tmp_path, payload),
            market_catalog=_catalog("US"),
            first_year=2026,
        )


def test_rejects_exceptional_close_outside_declared_year(tmp_path):
    payload = _payload()
    payload["markets"]["US"]["close_exceptions"]["2026"] = {
        "2027-11-26": "13:00:00"
    }

    with pytest.raises(ReviewedCalendarInputError, match="outside 2026"):
        ReviewedCalendarInput.load(
            _write(tmp_path, payload),
            market_catalog=_catalog("US"),
            first_year=2026,
        )


def test_rejects_exceptional_close_on_a_full_day_closure(tmp_path):
    payload = _payload()
    payload["markets"]["US"]["close_exceptions"]["2026"] = {
        "2026-01-01": "13:00:00"
    }

    with pytest.raises(ReviewedCalendarInputError, match="is also a closure"):
        ReviewedCalendarInput.load(
            _write(tmp_path, payload),
            market_catalog=_catalog("US"),
            first_year=2026,
        )


def test_production_input_covers_every_supported_market():
    reviewed = ReviewedCalendarInput.load(
        PRODUCTION_INPUT,
        market_catalog=get_market_catalog(),
        first_year=2026,
    )

    assert set(reviewed.markets) == set(
        get_market_catalog().supported_market_codes()
    )
