"""Year-over-year seasonality.

If the data reaches back far enough, the change between the baseline and the recent window *last year* tells how
much of this year's change is normal for the season. A page that lost 30% while the same weeks last year also lost
25% has really lost about 7%.
"""

from __future__ import annotations

from dataclasses import dataclass

from content_decay_finder.config import AnalysisConfig
from content_decay_finder.stats import clamp
from content_decay_finder.weekly import Series, Windows


@dataclass(frozen=True)
class SeasonalFactor:
    factor: float  # expected recent/baseline ratio of weekly clicks; 1.0 means "no seasonal change"
    source: str  # "page", "site" or "none"


NONE = SeasonalFactor(1.0, "none")


def yoy_ratio(series: Series, windows: Windows, min_clicks: float) -> float | None:
    if windows.yoy_recent is None or windows.yoy_baseline is None:
        return None
    base = series.window(*windows.yoy_baseline)
    recent = series.window(*windows.yoy_recent)
    if base.clicks < min_clicks:
        return None
    base_weeks = windows.yoy_baseline[1] - windows.yoy_baseline[0]
    recent_weeks = windows.yoy_recent[1] - windows.yoy_recent[0]
    return (recent.clicks / recent_weeks) / (base.clicks / base_weeks)


def seasonal_factor(page: Series, site: Series | None, windows: Windows, cfg: AnalysisConfig) -> SeasonalFactor:
    """Pick the expected recent/baseline ratio.

    - ``page``: the page's own year-over-year ratio (none if the page has too few clicks last year)
    - ``site``: the ratio of the whole site
    - ``auto``: the lower of the two. A page's own ratio also contains its long-term growth (a page that grew
      from 10 to 20 clicks last year "expects" another +100%), so a page is only flagged when it falls short of both
      its own seasonal pattern and the site's.
    """
    if cfg.seasonality == "off":
        return NONE
    low, high = cfg.seasonal_clamp
    page_ratio = yoy_ratio(page, windows, cfg.min_seasonal_clicks) if cfg.seasonality in ("auto", "page") else None
    site_ratio = (
        yoy_ratio(site, windows, cfg.min_seasonal_clicks)
        if site is not None and cfg.seasonality in ("auto", "site")
        else None
    )
    candidates = [(r, src) for r, src in ((page_ratio, "page"), (site_ratio, "site")) if r is not None]
    if not candidates:
        return NONE
    ratio, source = min(candidates, key=lambda c: c[0])
    return SeasonalFactor(clamp(ratio, low, high), source)
