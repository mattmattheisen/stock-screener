"""Backend-owned metadata for versioned scan-row materializations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MATERIALIZATION_VERSIONS_KEY = "materialization_versions"
OPPORTUNITY_STATE_MATERIALIZATION_VERSION = 1


def with_opportunity_state_materialization(
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a copied config marked as produced by the current policy stage."""
    result = dict(config or {})
    raw_versions = result.get(MATERIALIZATION_VERSIONS_KEY)
    versions = dict(raw_versions) if isinstance(raw_versions, Mapping) else {}
    versions["opportunity_state"] = OPPORTUNITY_STATE_MATERIALIZATION_VERSION
    result[MATERIALIZATION_VERSIONS_KEY] = versions
    return result


def config_has_opportunity_state_materialization(config: object) -> bool:
    """Return whether config explicitly owns the supported materialization."""
    if not isinstance(config, Mapping):
        return False
    versions = config.get(MATERIALIZATION_VERSIONS_KEY)
    return (
        isinstance(versions, Mapping)
        and versions.get("opportunity_state")
        == OPPORTUNITY_STATE_MATERIALIZATION_VERSION
    )


def scan_has_opportunity_state_materialization(scan: object) -> bool:
    """Resolve capability from the owning run, or direct-scan metadata.

    A feature-run binding is authoritative when present. Direct/compiled scan
    rows use reserved metadata in ``Scan.criteria``. Page contents are never
    inspected, so an empty current result and a legacy result remain distinct.
    """
    if getattr(scan, "feature_run_id", None) is not None:
        run = getattr(scan, "feature_run", None)
        run_config = getattr(run, "config_json", None)
        if run_config is None:
            run_config = getattr(run, "config", None)
        return config_has_opportunity_state_materialization(run_config)
    return config_has_opportunity_state_materialization(
        getattr(scan, "criteria", None)
    )


__all__ = [
    "MATERIALIZATION_VERSIONS_KEY",
    "OPPORTUNITY_STATE_MATERIALIZATION_VERSION",
    "config_has_opportunity_state_materialization",
    "scan_has_opportunity_state_materialization",
    "with_opportunity_state_materialization",
]
