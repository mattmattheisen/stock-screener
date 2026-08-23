"""Explicit ownership tests for scan-row materialization capability."""

from app.domain.scanning import materialization

CAPABLE = {"materialization_versions": {"opportunity_state": 1}}


def test_feature_run_config_is_authoritative_when_scan_is_bound():
    """Break caught: direct-scan metadata overriding an explicitly linked legacy run."""
    assert hasattr(materialization, "resolve_opportunity_state_capability")
    assert materialization.resolve_opportunity_state_capability(
        feature_run_id=7,
        feature_run_config={},
        scan_metadata=CAPABLE,
    ) is False


def test_direct_scan_uses_backend_metadata_without_criteria_fallback():
    """Break caught: internal capability leaking back into user-authored criteria."""
    assert materialization.resolve_opportunity_state_capability(
        feature_run_id=None,
        feature_run_config=None,
        scan_metadata=CAPABLE,
    ) is True
    assert materialization.resolve_opportunity_state_capability(
        feature_run_id=None,
        feature_run_config=None,
        scan_metadata=None,
    ) is False
