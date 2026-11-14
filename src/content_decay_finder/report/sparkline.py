"""Inline SVG sparklines (no JavaScript, no external files)."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape


def sparkline(
    values: Sequence[float | None],
    width: int = 120,
    height: int = 28,
    stroke: str = "#2563eb",
    invert: bool = False,
    label: str = "",
) -> str:
    """A polyline of ``values`` (``None`` gaps are skipped). ``invert`` puts low values at the top, for positions."""
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    title = f"<title>{escape(label)}</title>" if label else ""
    if len(points) < 2:
        return (
            f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="{escape(label or "no data")}">{title}</svg>'
        )
    n = max(len(values) - 1, 1)
    lo = min(v for _, v in points)
    hi = max(v for _, v in points)
    span = hi - lo or 1.0
    pad = 2.0

    def xy(i: int, v: float) -> tuple[float, float]:
        x = pad + (width - 2 * pad) * i / n
        frac = (v - lo) / span
        if invert:
            frac = 1 - frac
        y = height - pad - (height - 2 * pad) * frac
        return round(x, 1), round(y, 1)

    coords = [xy(i, v) for i, v in points]
    path = " ".join(f"{x},{y}" for x, y in coords)
    last_x, last_y = coords[-1]
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(label or "trend")}">{title}'
        f'<polyline fill="none" stroke="{escape(stroke)}" stroke-width="1.5" stroke-linejoin="round" '
        f'points="{path}"/><circle cx="{last_x}" cy="{last_y}" r="2" fill="{escape(stroke)}"/></svg>'
    )
