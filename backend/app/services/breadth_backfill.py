"""Typed planning and execution boundary for historical breadth backfills."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from .static_breadth_eligibility import static_breadth_eligibility_signature


@dataclass(frozen=True, slots=True)
class BreadthEligibleUniverse:
    """The exact eligible universe and provenance for one calculation date."""

    calculation_date: date
    symbols: tuple[str, ...]
    eligibility_signature: str


@dataclass(frozen=True, slots=True)
class BreadthBackfillPlan:
    """Validated dates and optional explicit universes for one backfill."""

    dates: tuple[date, ...]
    universes: Mapping[date, BreadthEligibleUniverse] | None = None

    @classmethod
    def from_legacy(
        cls,
        *,
        dates: Sequence[date],
        eligible_symbols_by_date: Mapping[date, Sequence[str]] | None,
        eligibility_signatures_by_date: Mapping[date, str] | None,
    ) -> "BreadthBackfillPlan":
        ordered_dates = tuple(sorted(set(dates)))
        has_symbols = eligible_symbols_by_date is not None
        has_signatures = eligibility_signatures_by_date is not None
        if has_symbols != has_signatures:
            raise ValueError(
                "eligible symbols and eligibility signatures must be supplied together"
            )
        if not has_symbols:
            return cls(dates=ordered_dates)

        assert eligible_symbols_by_date is not None
        assert eligibility_signatures_by_date is not None
        universes: dict[date, BreadthEligibleUniverse] = {}
        for calculation_date in ordered_dates:
            if calculation_date not in eligible_symbols_by_date:
                raise ValueError(
                    "eligible symbols missing for "
                    f"{calculation_date.isoformat()}"
                )
            if calculation_date not in eligibility_signatures_by_date:
                raise ValueError(
                    "eligibility signature missing for "
                    f"{calculation_date.isoformat()}"
                )
            symbols = tuple(
                sorted(set(eligible_symbols_by_date[calculation_date]))
            )
            expected_signature = static_breadth_eligibility_signature(symbols)
            supplied_signature = eligibility_signatures_by_date[calculation_date]
            if supplied_signature != expected_signature:
                raise ValueError(
                    "eligibility signature does not match canonical symbols for "
                    f"{calculation_date.isoformat()}"
                )
            universes[calculation_date] = BreadthEligibleUniverse(
                calculation_date=calculation_date,
                symbols=symbols,
                eligibility_signature=expected_signature,
            )
        return cls(
            dates=ordered_dates,
            universes=MappingProxyType(universes),
        )

    def universe_for(
        self,
        calculation_date: date,
    ) -> BreadthEligibleUniverse | None:
        if self.universes is None:
            return None
        return self.universes[calculation_date]
