"""Boundary tests for privacy-safe opportunity telemetry ingestion."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio

from app.main import app


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture(autouse=True)
def disable_server_auth(monkeypatch):
    from app.services import server_auth

    monkeypatch.setattr(server_auth.settings, "server_auth_enabled", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["scan", "daily", "watchlist"])
async def test_evidence_open_accepts_live_surfaces_and_records_only_market_and_surface(
    client, monkeypatch, surface
):
    from app.api.v1 import telemetry as telemetry_api

    telemetry = MagicMock()
    monkeypatch.setattr(telemetry_api, "get_telemetry", lambda: telemetry)

    response = await client.post(
        "/api/v1/telemetry/opportunity/evidence-open",
        json={"market": " us ", "surface": surface},
    )

    assert response.status_code == 204
    telemetry.record_opportunity_evidence_open.assert_called_once_with(
        "US", surface=surface
    )


@pytest.mark.asyncio
async def test_evidence_open_rejects_unknown_surface(client, monkeypatch):
    from app.api.v1 import telemetry as telemetry_api

    telemetry = MagicMock()
    monkeypatch.setattr(telemetry_api, "get_telemetry", lambda: telemetry)

    response = await client.post(
        "/api/v1/telemetry/opportunity/evidence-open",
        json={"market": "US", "surface": "other"},
    )

    assert response.status_code == 422
    telemetry.record_opportunity_evidence_open.assert_not_called()


@pytest.mark.asyncio
async def test_evidence_open_rejects_sensitive_extra_fields(client, monkeypatch):
    from app.api.v1 import telemetry as telemetry_api

    telemetry = MagicMock()
    monkeypatch.setattr(telemetry_api, "get_telemetry", lambda: telemetry)

    response = await client.post(
        "/api/v1/telemetry/opportunity/evidence-open",
        json={"market": "US", "surface": "scan", "symbol": "NVDA"},
    )

    assert response.status_code == 422
    telemetry.record_opportunity_evidence_open.assert_not_called()


@pytest.mark.asyncio
async def test_evidence_open_rejects_unknown_market(client, monkeypatch):
    from app.api.v1 import telemetry as telemetry_api

    telemetry = MagicMock()
    monkeypatch.setattr(telemetry_api, "get_telemetry", lambda: telemetry)

    response = await client.post(
        "/api/v1/telemetry/opportunity/evidence-open",
        json={"market": "XX", "surface": "scan"},
    )

    assert response.status_code == 404
    telemetry.record_opportunity_evidence_open.assert_not_called()


@pytest.mark.asyncio
async def test_evidence_open_swallows_counter_failure(client, monkeypatch):
    from app.api.v1 import telemetry as telemetry_api

    telemetry = MagicMock()
    telemetry.record_opportunity_evidence_open.side_effect = RuntimeError(
        "redis unavailable"
    )
    monkeypatch.setattr(telemetry_api, "get_telemetry", lambda: telemetry)

    response = await client.post(
        "/api/v1/telemetry/opportunity/evidence-open",
        json={"market": "US", "surface": "daily"},
    )

    assert response.status_code == 204
    telemetry.record_opportunity_evidence_open.assert_called_once_with(
        "US", surface="daily"
    )


@pytest.mark.asyncio
async def test_evidence_open_uses_existing_server_auth_guard(client, monkeypatch):
    from app.api.v1 import telemetry as telemetry_api
    from app.services import server_auth

    monkeypatch.setattr(server_auth.settings, "server_auth_enabled", True)
    monkeypatch.setattr(server_auth.settings, "server_auth_password", "secret-pass")
    monkeypatch.setattr(
        server_auth.settings,
        "server_auth_session_secret",
        "secret-signing-key",
    )
    telemetry = MagicMock()
    monkeypatch.setattr(telemetry_api, "get_telemetry", lambda: telemetry)

    unauthorized = await client.post(
        "/api/v1/telemetry/opportunity/evidence-open",
        json={"market": "US", "surface": "scan"},
    )
    authorized = await client.post(
        "/api/v1/telemetry/opportunity/evidence-open",
        headers={"X-Server-Auth": "secret-pass"},
        json={"market": "US", "surface": "scan"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 204
    telemetry.record_opportunity_evidence_open.assert_called_once_with(
        "US", surface="scan"
    )
