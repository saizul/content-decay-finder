"""Small statistics helpers (no numpy needed)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Trend:
    slope: float  # units per week
    intercept: float
    r2: float
    mean: float

    @property
    def relative_slope(self) -> float:
        """Slope as a fraction of the mean per week (-0.05 = losing 5% of the average every week)."""
        return self.slope / self.mean if self.mean else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def linear_trend(values: Sequence[float]) -> Trend:
    """Ordinary least squares over x = 0, 1, 2, ... (one point per week)."""
    n = len(values)
    if n == 0:
        return Trend(0.0, 0.0, 0.0, 0.0)
    y_mean = mean(values)
    if n == 1:
        return Trend(0.0, y_mean, 0.0, y_mean)
    x_mean = (n - 1) / 2
    sxx = sum((x - x_mean) ** 2 for x in range(n))
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in enumerate(values))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    ss_tot = sum((y - y_mean) ** 2 for y in values)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in enumerate(values))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return Trend(slope, intercept, max(0.0, r2), y_mean)


def theil_sen_slope(values: Sequence[float]) -> float:
    """Median of pairwise slopes: robust against a single outlier week."""
    slopes = sorted((values[j] - values[i]) / (j - i) for i in range(len(values)) for j in range(i + 1, len(values)))
    if not slopes:
        return 0.0
    mid = len(slopes) // 2
    return slopes[mid] if len(slopes) % 2 else (slopes[mid - 1] + slopes[mid]) / 2


def pct_change(before: float, after: float) -> float | None:
    if before == 0:
        return None if after == 0 else math.inf
    return (after - before) / before


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
