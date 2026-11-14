"""Run the whole analysis on a dataset."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from content_decay_finder._version import __version__
from content_decay_finder.cannibalization import CannibalCase, find_cannibalization
from content_decay_finder.config import AnalysisConfig, ConfigError
from content_decay_finder.decay import PageResult, analyze_page, normalize_priorities, window_dates
from content_decay_finder.loader import Dataset
from content_decay_finder.model import Row
from content_decay_finder.opportunities import Opportunity, ctr_curve, find_opportunities
from content_decay_finder.seasonality import seasonal_factor
from content_decay_finder.sections import SectionResult, summarize_sections
from content_decay_finder.stats import linear_trend, pct_change
from content_decay_finder.urls import section_of
from content_decay_finder.weekly import Series, build_series, full_weeks, make_windows


class AnalysisError(ValueError):
    pass


@dataclass
class SiteSummary:
    pages: int
    baseline_clicks: float
    recent_clicks: float
    clicks_change: float | None
    adjusted_change: float | None
    seasonal_factor: float
    seasonal_source: str
    weekly_clicks: list[float]
    weekly_impressions: list[float]
    status_counts: dict[str, int]
    lost_clicks: float

    def to_dict(self) -> dict[str, Any]:
        def r(v: float | None, d: int = 4) -> float | None:
            return None if v is None or v == float("inf") else round(v, d)

        return {
            "pages": self.pages,
            "baseline_clicks_weekly": r(self.baseline_clicks, 2),
            "recent_clicks_weekly": r(self.recent_clicks, 2),
            "clicks_change": r(self.clicks_change),
            "adjusted_change": r(self.adjusted_change),
            "seasonal_factor": r(self.seasonal_factor, 3),
            "seasonal_source": self.seasonal_source,
            "status_counts": self.status_counts,
            "lost_clicks": r(self.lost_clicks, 1),
            "weekly_clicks": [round(v, 1) for v in self.weekly_clicks],
            "weekly_impressions": [round(v, 1) for v in self.weekly_impressions],
        }


@dataclass
class AnalysisResult:
    config: AnalysisConfig
    first_date: date
    last_date: date
    weeks: list[date]
    windows: dict[str, str]
    site: SiteSummary
    pages: list[PageResult]
    sections: list[SectionResult]
    cannibalization: list[CannibalCase]
    opportunities: list[Opportunity]
    query_opportunities: list[Opportunity]
    ctr_curve: dict[int, float]
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    has_queries: bool = False

    @property
    def decaying(self) -> list[PageResult]:
        return [p for p in self.pages if p.status == "decaying"]

    @property
    def watch(self) -> list[PageResult]:
        return [p for p in self.pages if p.status == "watch"]

    def ranked(self) -> list[PageResult]:
        """Decaying and watch pages, highest refresh priority first."""
        flagged = [p for p in self.pages if p.status in ("decaying", "watch")]
        return sorted(flagged, key=lambda p: (-p.priority_raw, -p.lost_clicks, p.page))

    def to_dict(self, top: int | None = None) -> dict[str, Any]:
        limit = top if top is not None else self.config.top
        return {
            "tool": "content-decay-finder",
            "version": __version__,
            "data": {
                "first_date": self.first_date.isoformat(),
                "last_date": self.last_date.isoformat(),
                "full_weeks": len(self.weeks),
                "windows": self.windows,
                "sources": self.sources,
            },
            "settings": {
                "recent_weeks": self.config.recent_weeks,
                "baseline_weeks": self.config.baseline_weeks,
                "trend_weeks": self.config.trend_weeks,
                "decline_threshold": self.config.decline_threshold,
                "seasonality": self.config.seasonality,
                "section_depth": self.config.section_depth,
            },
            "notes": self.notes,
            "site": self.site.to_dict(),
            "refresh_priorities": [p.to_dict() for p in self.ranked()[:limit]],
            "sections": [s.to_dict() for s in self.sections],
            "cannibalization": [c.to_dict() for c in self.cannibalization[:limit]],
            "almost_page_one": [o.to_dict() for o in self.opportunities[:limit]],
            "almost_page_one_queries": [o.to_dict() for o in self.query_opportunities[:limit]],
            "ctr_curve": {str(k): round(v, 4) for k, v in self.ctr_curve.items()},
        }


def _filter(rows: list[Row], cfg: AnalysisConfig) -> list[Row]:
    if not cfg.ignore_patterns:
        return rows
    return [r for r in rows if not any(p.search(r.page) for p in cfg.ignore_patterns)]


def analyze(dataset: Dataset, cfg: AnalysisConfig | None = None) -> AnalysisResult:
    cfg = cfg or AnalysisConfig()
    cfg.validate()
    page_rows = _filter(dataset.page_rows, cfg)
    query_rows = _filter(dataset.query_rows, cfg)
    if not page_rows:
        raise AnalysisError("no rows to analyse")
    first = min(r.date for r in page_rows)
    last = max(r.date for r in page_rows)
    weeks = full_weeks(first, last)
    windows = make_windows(len(weeks), cfg.recent_weeks, cfg.baseline_weeks, cfg.trend_weeks)
    if windows is None:
        raise AnalysisError(
            f"the data covers {len(weeks)} full week(s) ({first} to {last}); at least "
            f"{cfg.recent_weeks + cfg.baseline_weeks} are needed (recent + baseline weeks)"
        )
    notes: list[str] = []
    if dataset.page_level_derived:
        notes.append(
            "Page totals were summed from query rows; Search Console leaves out anonymised queries, so clicks and "
            "impressions are lower than the real page totals."
        )
    if windows.yoy_recent is None and cfg.seasonality != "off":
        notes.append(
            f"Seasonality was not adjusted: year-over-year needs {cfg.recent_weeks + cfg.baseline_weeks + 52} full "
            f"weeks of data, this data has {len(weeks)}."
        )
    series = build_series(page_rows, weeks)
    site = build_series(page_rows, weeks, key=lambda r: "__site__")["__site__"]
    results = [
        analyze_page(page, section_of(page, cfg.section_depth, cfg.section_rules), s, site, windows, cfg)
        for page, s in series.items()
    ]
    normalize_priorities(results)
    results.sort(key=lambda p: p.page)

    site_factor = seasonal_factor(site, None, windows, cfg) if cfg.seasonality != "off" else None
    rw = windows.recent[1] - windows.recent[0]
    bw = windows.baseline[1] - windows.baseline[0]
    base_weekly = site.window(*windows.baseline).clicks / bw
    recent_weekly = site.window(*windows.recent).clicks / rw
    factor = site_factor.factor if site_factor else 1.0
    counts: dict[str, int] = {}
    for p in results:
        counts[p.status] = counts.get(p.status, 0) + 1
    t0, t1 = windows.trend
    summary = SiteSummary(
        pages=len(results),
        baseline_clicks=base_weekly,
        recent_clicks=recent_weekly,
        clicks_change=pct_change(base_weekly, recent_weekly),
        adjusted_change=pct_change(base_weekly * factor, recent_weekly),
        seasonal_factor=factor,
        seasonal_source=site_factor.source if site_factor and site_factor.source != "none" else "none",
        weekly_clicks=site.clicks()[t0:t1],
        weekly_impressions=site.impressions()[t0:t1],
        status_counts=dict(sorted(counts.items())),
        lost_clicks=sum(p.lost_clicks for p in results if p.status in ("decaying", "watch")),
    )
    if linear_trend(site.clicks()[t0:t1]).relative_slope < -0.02:
        notes.append(
            "Clicks for the whole site are trending down; check for an algorithm update or a technical "
            "problem (indexing, robots.txt, redirects) before refreshing single pages."
        )

    curve = ctr_curve(page_rows)
    sections = summarize_sections(results)
    cannibal = find_cannibalization(query_rows, weeks, windows.baseline, windows.recent, cfg) if query_rows else []
    opportunities = find_opportunities(page_rows, weeks, windows.recent, cfg, curve, by_query=False)
    query_opps = find_opportunities(query_rows, weeks, windows.recent, cfg, curve, by_query=True) if query_rows else []
    if not query_rows:
        notes.append("No query-level data: cannibalisation needs rows with date, page and query.")
    return AnalysisResult(
        config=cfg,
        first_date=first,
        last_date=last,
        weeks=weeks,
        windows=window_dates(weeks, windows),
        site=summary,
        pages=results,
        sections=sections,
        cannibalization=cannibal,
        opportunities=opportunities,
        query_opportunities=query_opps,
        ctr_curve=curve,
        notes=notes,
        sources=dataset.sources,
        has_queries=bool(query_rows),
    )


def series_for(dataset: Dataset, page: str) -> Series | None:  # pragma: no cover - convenience for library users
    rng = dataset.date_range
    if rng is None:
        return None
    weeks = full_weeks(*rng)
    return build_series([r for r in dataset.page_rows if r.page == page], weeks).get(page)


__all__ = ["AnalysisError", "AnalysisResult", "ConfigError", "SiteSummary", "analyze"]
