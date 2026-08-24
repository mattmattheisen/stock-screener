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


def resolve_opportunity_state_capability(
    *,
    feature_run_id: int | None,
    feature_run_config: Mapping[str, Any] | None,
    scan_metadata: Mapping[str, Any] | None,
) -> bool:
    """Resolve capability from its explicit authoritative owner."""
    source = feature_run_config if feature_run_id is not None else scan_metadata
    return config_has_opportunity_state_materialization(source)


__all__ = [
    "MATERIALIZATION_VERSIONS_KEY",
    "OPPORTUNITY_STATE_MATERIALIZATION_VERSION",
    "config_has_opportunity_state_materialization",
    "resolve_opportunity_state_capability",
    "with_opportunity_state_materialization",
]
