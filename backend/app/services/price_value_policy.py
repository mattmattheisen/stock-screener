"""Shared validity checks for persisted market price values."""

from __future__ import annotations

from app.infra.serialization import finite_float_or_none


def is_usable_adjusted_close(value: object) -> bool:
    price = finite_float_or_none(value)
    return price is not None and price > 0


def protect_existing_adjusted_close(
    incoming: dict[str, object],
    existing_adjusted_close: object,
    *,
    existing_raw_close: object | None = None,
) -> dict[str, object]:
    """Preserve a usable adjustment only when the raw close is unchanged.

    This is a *loss-prevention* rule only. The persisted value might itself
    be legacy raw-close fallback; provenance must be audited separately.
    """
    merged = dict(incoming)
    # If the raw price was corrected, an old adjusted value may no longer
    # correspond to the new session price; leave it missing for audit.
    existing_raw = finite_float_or_none(existing_raw_close)
    incoming_raw = finite_float_or_none(merged.get('close'))
    unchanged_raw = (existing_raw is None or (
        incoming_raw is not None and abs(existing_raw - incoming_raw) <= 1e-8
    ))
    if (unchanged_raw and not is_usable_adjusted_close(merged.get("adj_close"))
            and is_usable_adjusted_close(existing_adjusted_close)):
        merged["adj_close"] = existing_adjusted_close
    return merged


__all__ = ["is_usable_adjusted_close", "protect_existing_adjusted_close"]
