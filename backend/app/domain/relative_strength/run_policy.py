from collections.abc import Mapping

BALANCED_RS_PRICE_BASIS = "adj_close_only"
BALANCED_RS_SNAPSHOT_SCHEMA_VERSION = 2


def balanced_run_has_current_snapshot_contract(run) -> bool:
    """Return whether a balanced run uses the current persisted snapshot contract."""
    diagnostics = getattr(run, "diagnostics_json", None)
    return (
        isinstance(diagnostics, Mapping)
        and diagnostics.get("price_basis") == BALANCED_RS_PRICE_BASIS
        and diagnostics.get("rs_snapshot_schema_version")
        == BALANCED_RS_SNAPSHOT_SCHEMA_VERSION
    )


def balanced_run_has_required_price_basis(run) -> bool:
    """Backward-compatible alias for the current balanced snapshot contract."""
    return balanced_run_has_current_snapshot_contract(run)
