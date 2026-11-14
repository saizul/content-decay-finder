"""Number formatting shared by the text reports."""

from __future__ import annotations

import math


def pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    if math.isinf(value):
        return "new"
    if abs(value) < 0.005:
        return "0%"
    return f"{value * 100:+.0f}%" if signed else f"{value * 100:.0f}%"


def num(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def pos(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def delta_pos(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}"
