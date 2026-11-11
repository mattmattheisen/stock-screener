"""Point-in-time price and supply/demand measures for research, not production."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class PriceVolumeResult:
    high_52w: float
    distance_from_high_pct: float
    up_down_volume_ratio: float | None
    up_volume: float
    down_volume: float
    n_10_pass: bool
    n_15_pass: bool
    s_13_pass: bool | None


def calculate(closes: Sequence[float], highs: Sequence[float], volumes: Sequence[float], *, lookback: int = 252, volume_days: int = 50) -> PriceVolumeResult:
    """Chronological oldest-to-newest data, all ending at decision close.

    Use observed daily HIGH for 52-week reference; require full history.
    Up/down volume is classified using prior-close to current-close change.
    A zero down-volume denominator is unavailable, not an infinite pass.
    """
    if not (len(closes) == len(highs) == len(volumes)):
        raise ValueError('Misaligned OHLCV lengths')
    if len(closes) < max(lookback, volume_days + 1):
        raise ValueError('Insufficient point-in-time OHLCV history')
    if any(not (isfinite(float(c)) and isfinite(float(h)) and isfinite(float(v))) or c <= 0 or h <= 0 or v < 0 or c > h for c, h, v in zip(closes, highs, volumes)):
        raise ValueError('Invalid OHLCV observation')
    reference_high = max(highs[-lookback:])
    distance = 100.0 * (reference_high - closes[-1]) / reference_high
    up = down = 0.0
    start = len(closes) - volume_days
    for i in range(start, len(closes)):
        if closes[i] > closes[i - 1]:
            up += volumes[i]
        elif closes[i] < closes[i - 1]:
            down += volumes[i]
    ratio = up / down if down > 0 else None
    return PriceVolumeResult(reference_high, distance, ratio, up, down, distance <= 10, distance <= 15, ratio >= 1.3 if ratio is not None else None)
