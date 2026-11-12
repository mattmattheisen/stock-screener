"""Shared validity checks for persisted market price values."""

from __future__ import annotations

from app.infra.serialization import finite_float_or_none


def is_usable_adjusted_close(value: object) -> bool:
    price = finite_float_or_none(value)
    return price is not None and price > 0


def protect_existing_adjusted_close(
    incoming: dict[str, object],
    existing_adjusted_close: object,
) -> dict[str, object]:
    """Prevent an incomplete refresh from erasing an existing usable adj_close.

    This is a *loss-prevention* rule only. The persisted value might itself
    be legacy raw-close fallback; provenance must be audited separately.
    """
    merged = dict(incoming)
    if (not is_usable_adjusted_close(merged.get("adj_close"))
            and is_usable_adjusted_close(existing_adjusted_close)):
        merged["adj_close"] = existing_adjusted_close
    return merged


__all__ = ["is_usable_adjusted_close", "protect_existing_adjusted_close"]
