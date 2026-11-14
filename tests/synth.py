"""Deterministic synthetic Search Console data for the tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from content_decay_finder.loader import Dataset
from content_decay_finder.model import Row

START = date(2025, 1, 6)  # a Monday
SITE = "https://www.example.com"

# week index -> (clicks per day, impressions per day, position)
Pattern = Callable[[int], tuple[float, float, float]]


def daily_rows(
    page: str, pattern: Pattern, weeks: int, start: date = START, query: str | None = None, first_week: int = 0
) -> list[Row]:
    rows = []
    for w in range(first_week, weeks):
        clicks, impressions, position = pattern(w)
        for d in range(7):
            day = start + timedelta(days=7 * w + d)
            rows.append(Row(day, page, clicks, impressions, position, query))
    return rows


def steady(clicks: float = 50, impressions: float = 1000, position: float = 4.0) -> Pattern:
    return lambda w: (clicks, impressions, position)


def decaying(weeks: int, start_decline: int, clicks: float = 60, floor: float = 0.4) -> Pattern:
    """Steady, then a linear decline from start_decline to the end (down to ``floor`` of the original),
    with impressions falling a bit and the position slipping."""

    def pattern(w: int) -> tuple[float, float, float]:
        if w < start_decline:
            return clicks, 1500, 3.0
        frac = (w - start_decline + 1) / (weeks - start_decline)
        factor = 1 - (1 - floor) * frac
        return clicks * factor, 1500 * (1 - 0.3 * frac), 3.0 + 4 * frac

    return pattern


def ctr_drop(weeks: int, start_drop: int) -> Pattern:
    return lambda w: (40.0 if w < start_drop else 40.0 * (0.85 ** (w - start_drop + 1)), 800.0, 2.5)


def growing(weeks: int) -> Pattern:
    return lambda w: (10 + w * 1.5, 500 + w * 20, 6.0)


def seasonal(period_weeks: int = 52, low_start: int = 44, low_len: int = 8, clicks: float = 50) -> Pattern:
    """Clicks drop to 40% for ``low_len`` weeks every year starting at week ``low_start`` of the cycle."""

    def pattern(w: int) -> tuple[float, float, float]:
        in_low = low_start <= (w % period_weeks) < low_start + low_len
        factor = 0.4 if in_low else 1.0
        return clicks * factor, 1000 * factor, 4.0

    return pattern


def page(path: str) -> str:
    return f"{SITE}{path}"


def standard_dataset(weeks: int = 30) -> Dataset:
    ds = Dataset(sources=["synthetic"])
    ds.page_rows += daily_rows(page("/blog/decaying-guide/"), decaying(weeks, weeks - 10), weeks)
    ds.page_rows += daily_rows(page("/blog/ctr-drop/"), ctr_drop(weeks, weeks - 4), weeks)
    ds.page_rows += daily_rows(page("/blog/growing/"), growing(weeks), weeks)
    ds.page_rows += daily_rows(page("/products/widget"), steady(), weeks)
    ds.page_rows += daily_rows(page("/products/tiny"), steady(0.2, 20, 30), weeks)
    ds.page_rows += daily_rows(page("/guides/almost/"), steady(3, 300, 12.5), weeks)
    ds.page_rows += daily_rows(page("/new-page"), steady(20, 400, 5), weeks, first_week=weeks - 4)
    ds.page_rows += daily_rows(page("/"), steady(100, 2000, 1.5), weeks)
    # "best widget": the leading page alternates every week
    for w in range(weeks):
        leader, other = (
            ("/products/widget", "/blog/widget-review/") if w % 2 else ("/blog/widget-review/", "/products/widget")
        )
        ds.query_rows += daily_rows(page(leader), lambda _w: (5, 60, 6.0), w + 1, query="best widget", first_week=w)
        ds.query_rows += daily_rows(page(other), lambda _w: (2, 40, 9.0), w + 1, query="best widget", first_week=w)
    # a stable query on one page only
    ds.query_rows += daily_rows(page("/"), steady(30, 400, 1.2), weeks, query="example brand")
    # page+query in the almost-page-1 range
    ds.query_rows += daily_rows(page("/guides/almost/"), steady(2, 200, 11.0), weeks, query="widget guide")
    return ds.finalize()
