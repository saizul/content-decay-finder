"""Weekly buckets (ISO weeks, Monday to Sunday) and the analysis windows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from content_decay_finder.model import Row, Totals


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def full_weeks(first: date, last: date) -> list[date]:
    """Mondays of the weeks fully covered by [first, last]. Partial weeks at either end are dropped, so a week
    that Search Console has not finished processing does not look like a drop."""
    start = first if first.weekday() == 0 else week_start(first) + timedelta(days=7)
    end = week_start(last) if last.weekday() == 6 else week_start(last) - timedelta(days=7)
    weeks = []
    current = start
    while current <= end:
        weeks.append(current)
        current += timedelta(days=7)
    return weeks


@dataclass
class Series:
    """Weekly totals for one key (a page, a section, the whole site) aligned to a shared list of weeks."""

    weeks: list[date]
    totals: list[Totals]

    def clicks(self) -> list[float]:
        return [t.clicks for t in self.totals]

    def impressions(self) -> list[float]:
        return [t.impressions for t in self.totals]

    def positions(self) -> list[float | None]:
        return [t.position for t in self.totals]

    def window(self, start: int, end: int) -> Totals:
        out = Totals()
        for t in self.totals[max(0, start) : end]:
            out.merge(t)
        return out


def build_series(rows: Iterable[Row], weeks: list[date], key=lambda r: r.page) -> dict[str, Series]:
    index = {w: i for i, w in enumerate(weeks)}
    buckets: dict[str, list[Totals]] = defaultdict(lambda: [Totals() for _ in weeks])
    for row in rows:
        i = index.get(week_start(row.date))
        if i is None:
            continue
        buckets[key(row)][i].add(row.clicks, row.impressions, row.position)
    return {k: Series(weeks, v) for k, v in buckets.items()}


@dataclass(frozen=True)
class Windows:
    """Index ranges into the week list: [start, end)."""

    recent: tuple[int, int]
    baseline: tuple[int, int]
    trend: tuple[int, int]
    yoy_recent: tuple[int, int] | None
    yoy_baseline: tuple[int, int] | None

    def label(self, weeks: list[date], which: str) -> str:
        span = getattr(self, which)
        if span is None:
            return "-"
        first = weeks[span[0]]
        last = weeks[span[1] - 1] + timedelta(days=6)
        return f"{first.isoformat()} to {last.isoformat()}"


def make_windows(n_weeks: int, recent: int, baseline: int, trend: int) -> Windows | None:
    if n_weeks < recent + baseline:
        return None
    r = (n_weeks - recent, n_weeks)
    b = (n_weeks - recent - baseline, n_weeks - recent)
    t = (max(0, n_weeks - trend), n_weeks)
    yoy_r = yoy_b = None
    if b[0] - 52 >= 0:  # 52 weeks back keeps weekdays aligned
        yoy_r = (r[0] - 52, r[1] - 52)
        yoy_b = (b[0] - 52, b[1] - 52)
    return Windows(r, b, t, yoy_r, yoy_b)
