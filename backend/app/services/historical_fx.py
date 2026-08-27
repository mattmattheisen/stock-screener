"""Pure historical-FX resolution shared by non-breadth currency consumers."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date

import numpy as np
import pandas as pd


class MissingHistoricalFXError(RuntimeError):
    def __init__(self, currency: str, calculation_date: date) -> None:
        self.currency = currency
        self.calculation_date = calculation_date
        super().__init__(
            f"Missing historical {currency}->USD FX rate for "
            f"{calculation_date.isoformat()}"
        )


def resolve_historical_fx_series(
    currency: str,
    calculation_dates: Collection[date],
    observations: Mapping[date, float],
    *,
    max_age_days: int,
) -> pd.Series:
    normalized_currency = currency.strip().upper()
    requested = tuple(calculation_dates)
    index = pd.DatetimeIndex(requested)
    if normalized_currency == "USD":
        return pd.Series(1.0, index=index, dtype=float)

    valid_observations = sorted(
        (observation_date, float(rate))
        for observation_date, rate in observations.items()
        if rate is not None and np.isfinite(float(rate)) and float(rate) > 0
    )

    resolved: list[float] = []
    for requested_date in requested:
        prior = [item for item in valid_observations if item[0] <= requested_date]
        if not prior:
            raise MissingHistoricalFXError(normalized_currency, requested_date)
        observation_date, rate = prior[-1]
        if (requested_date - observation_date).days > max_age_days:
            raise MissingHistoricalFXError(normalized_currency, requested_date)
        resolved.append(rate)

    return pd.Series(resolved, index=index, dtype=float)
