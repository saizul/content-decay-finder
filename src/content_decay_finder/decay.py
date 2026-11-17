"""Per-page decay detection: period comparison, weekly trend, seasonality, causes and refresh priority."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from content_decay_finder.config import AnalysisConfig
from content_decay_finder.seasonality import SeasonalFactor, seasonal_factor
from content_decay_finder.stats import Trend, linear_trend, pct_change
from content_decay_finder.weekly import Series, Windows

STATUSES = ("decaying", "watch", "stable", "growing", "new", "low-data")


@dataclass
class PageResult:
    page: str
    section: str
    status: str
    baseline_clicks: float  # weekly average
    recent_clicks: float  # weekly average
    expected_clicks: float  # weekly average expected from baseline x seasonal factor
    clicks_change: float | None  # raw recent vs baseline
    adjusted_change: float | None  # recent vs expected (after seasonality)
    baseline_impressions: float
    recent_impressions: float
    impressions_change: float | None
    baseline_position: float | None
    recent_position: float | None
    position_change: float | None  # positive = worse (higher number)
    baseline_ctr: float
    recent_ctr: float
    ctr_change: float | None
    clicks_trend: Trend
    impressions_trend: Trend
    position_trend: Trend
    seasonal: SeasonalFactor
    lost_clicks: float  # clicks lost over the recent window compared with expectation
    steepness: float  # share of the trend-window average lost per week
    current_impressions: float  # total in the recent window
    priority_raw: float = 0.0
    priority: float = 0.0
    causes: list[str] = field(default_factory=list)
    weekly_clicks: list[float] = field(default_factory=list)
    weekly_impressions: list[float] = field(default_factory=list)
    weekly_position: list[float | None] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)  # old URLs folded into this page by a redirect map

    def to_dict(self) -> dict[str, object]:
        def r(value: float | None, digits: int = 4) -> float | None:
            if value is None or (isinstance(value, float) and not math.isfinite(value)):
                return None
            return round(value, digits)

        return {
            "page": self.page,
            "section": self.section,
            "status": self.status,
            "priority": r(self.priority, 1),
            "priority_raw": r(self.priority_raw, 2),
            "lost_clicks": r(self.lost_clicks, 1),
            "steepness": r(self.steepness),
            "causes": self.causes,
            "merged_from": self.merged_from,
            "clicks": {
                "baseline_weekly": r(self.baseline_clicks, 2),
                "recent_weekly": r(self.recent_clicks, 2),
                "expected_weekly": r(self.expected_clicks, 2),
                "change": r(self.clicks_change),
                "adjusted_change": r(self.adjusted_change),
                "trend_slope_weekly": r(self.clicks_trend.slope, 3),
                "trend_relative_slope": r(self.clicks_trend.relative_slope),
                "trend_r2": r(self.clicks_trend.r2, 3),
            },
            "impressions": {
                "baseline_weekly": r(self.baseline_impressions, 1),
                "recent_weekly": r(self.recent_impressions, 1),
                "recent_total": r(self.current_impressions, 0),
                "change": r(self.impressions_change),
                "trend_relative_slope": r(self.impressions_trend.relative_slope),
            },
            "position": {
                "baseline": r(self.baseline_position, 2),
                "recent": r(self.recent_position, 2),
                "change": r(self.position_change, 2),
                "trend_slope_weekly": r(self.position_trend.slope, 3),
            },
            "ctr": {"baseline": r(self.baseline_ctr), "recent": r(self.recent_ctr), "change": r(self.ctr_change)},
            "seasonality": {"factor": r(self.seasonal.factor, 3), "source": self.seasonal.source},
            "weekly": {
                "clicks": [r(v, 1) for v in self.weekly_clicks],
                "impressions": [r(v, 1) for v in self.weekly_impressions],
                "position": [r(v, 2) for v in self.weekly_position],
            },
        }


def _first_active_week(series: Series) -> int | None:
    for i, t in enumerate(series.totals):
        if t.impressions > 0:
            return i
    return None


def classify(result: PageResult, cfg: AnalysisConfig, baseline_total: float) -> str:
    adjusted = result.adjusted_change
    if baseline_total < cfg.min_baseline_clicks:
        return "low-data"
    if adjusted is None:
        return "stable"
    if adjusted <= -cfg.decline_threshold and result.steepness > 0:
        return "decaying"
    if adjusted <= -cfg.watch_threshold or (adjusted < 0 and result.steepness > 0.02 and result.clicks_trend.r2 >= 0.5):
        return "watch"
    if adjusted >= cfg.growth_threshold:
        return "growing"
    return "stable"


def find_causes(result: PageResult, cfg: AnalysisConfig) -> list[str]:
    causes = []
    if result.position_change is not None and result.position_change >= cfg.position_drop:
        causes.append("position")
    if result.impressions_change is not None and result.impressions_change <= -cfg.decline_threshold:
        causes.append("impressions")
    position_steady = result.position_change is None or result.position_change < cfg.position_drop
    if result.ctr_change is not None and result.ctr_change <= -cfg.decline_threshold and position_steady:
        causes.append("ctr")
    if result.seasonal.factor < 1 - cfg.watch_threshold:
        causes.append("seasonal")
    return causes


def analyze_page(
    page: str,
    section: str,
    series: Series,
    site: Series | None,
    windows: Windows,
    cfg: AnalysisConfig,
) -> PageResult:
    rw = windows.recent[1] - windows.recent[0]
    bw = windows.baseline[1] - windows.baseline[0]
    base = series.window(*windows.baseline)
    recent = series.window(*windows.recent)
    seasonal = seasonal_factor(series, site, windows, cfg)
    baseline_weekly = base.clicks / bw
    recent_weekly = recent.clicks / rw
    expected_weekly = baseline_weekly * seasonal.factor
    t0, t1 = windows.trend
    clicks_trend = linear_trend(series.clicks()[t0:t1])
    impressions_trend = linear_trend(series.impressions()[t0:t1])
    positions = [p for p in series.positions()[t0:t1] if p is not None]
    position_trend = linear_trend(positions)
    # steepness: share of the average lost per week, scaled by how well the line fits
    steepness = max(0.0, -clicks_trend.relative_slope) * clicks_trend.r2 if clicks_trend.mean else 0.0
    lost = max(0.0, (expected_weekly - recent_weekly) * rw)
    position_change = None
    if base.position is not None and recent.position is not None:
        position_change = recent.position - base.position
    result = PageResult(
        page=page,
        section=section,
        status="stable",
        baseline_clicks=baseline_weekly,
        recent_clicks=recent_weekly,
        expected_clicks=expected_weekly,
        clicks_change=pct_change(baseline_weekly, recent_weekly),
        adjusted_change=pct_change(expected_weekly, recent_weekly),
        baseline_impressions=base.impressions / bw,
        recent_impressions=recent.impressions / rw,
        impressions_change=pct_change(base.impressions / bw, recent.impressions / rw),
        baseline_position=base.position,
        recent_position=recent.position,
        position_change=position_change,
        baseline_ctr=base.ctr,
        recent_ctr=recent.ctr,
        ctr_change=pct_change(base.ctr, recent.ctr) if base.impressions and recent.impressions else None,
        clicks_trend=clicks_trend,
        impressions_trend=impressions_trend,
        position_trend=position_trend,
        seasonal=seasonal,
        lost_clicks=lost,
        steepness=steepness,
        current_impressions=recent.impressions,
        weekly_clicks=series.clicks()[t0:t1],
        weekly_impressions=series.impressions()[t0:t1],
        weekly_position=series.positions()[t0:t1],
    )
    first = _first_active_week(series)
    # first impressions in the second half of the baseline (or later): too young to judge against a baseline
    if first is not None and first >= windows.baseline[0] + bw // 2:
        result.status = "new"
    else:
        result.status = classify(result, cfg, base.clicks)
    if result.status in ("decaying", "watch"):
        result.causes = find_causes(result, cfg)
    # Refresh priority: lost clicks x trend steepness x current impressions
    if result.status in ("decaying", "watch"):
        result.priority_raw = result.lost_clicks * result.steepness * result.current_impressions
    return result


def normalize_priorities(results: list[PageResult]) -> None:
    """Scale raw priorities to 0-100 on a log scale (raw values span many orders of magnitude)."""
    top = max((r.priority_raw for r in results), default=0.0)
    if top <= 0:
        return
    for r in results:
        r.priority = 100 * math.log1p(r.priority_raw) / math.log1p(top) if r.priority_raw > 0 else 0.0


def window_dates(weeks: list[date], windows: Windows) -> dict[str, str]:
    return {name: windows.label(weeks, name) for name in ("baseline", "recent", "trend", "yoy_baseline", "yoy_recent")}
