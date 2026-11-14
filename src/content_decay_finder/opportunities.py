""" "Almost page 1": pages and queries ranking just below the top results, with an estimate of the clicks a move
up would bring."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from content_decay_finder.config import AnalysisConfig
from content_decay_finder.model import Row, Totals
from content_decay_finder.weekly import week_start

# Rough organic CTR by position, used only where the site's own data is too thin. Real curves vary a lot with the
# query type and SERP features; the site's own curve (see ctr_curve) is preferred.
DEFAULT_CTR = {1: 0.28, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05, 6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.017}


def ctr_curve(rows: Iterable[Row], min_impressions: float = 500.0) -> dict[int, float]:
    """The site's own CTR per rounded position 1-10 (impression-weighted), filled in from DEFAULT_CTR where a
    position has too few impressions, then made non-increasing."""
    buckets: dict[int, Totals] = defaultdict(Totals)
    for r in rows:
        if r.position is None or r.impressions <= 0:
            continue
        pos = round(r.position)
        if 1 <= pos <= 10:
            buckets[pos].add(r.clicks, r.impressions, r.position)
    curve = {}
    for pos in range(1, 11):
        t = buckets.get(pos)
        curve[pos] = t.ctr if t is not None and t.impressions >= min_impressions else DEFAULT_CTR[pos]
    running = 1.0
    for pos in range(1, 11):
        running = min(running, curve[pos])
        curve[pos] = running
    return curve


@dataclass
class Opportunity:
    page: str
    query: str | None
    impressions: float
    clicks: float
    position: float
    ctr: float
    target_ctr: float
    extra_clicks: float  # estimated, for the recent window

    def to_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "query": self.query,
            "impressions": round(self.impressions, 1),
            "clicks": round(self.clicks, 1),
            "position": round(self.position, 2),
            "ctr": round(self.ctr, 4),
            "target_ctr": round(self.target_ctr, 4),
            "extra_clicks": round(self.extra_clicks, 1),
        }


def find_opportunities(
    rows: Iterable[Row],
    weeks: list[date],
    recent: tuple[int, int],
    cfg: AnalysisConfig,
    curve: dict[int, float],
    by_query: bool,
) -> list[Opportunity]:
    if not weeks:
        return []
    first, last = weeks[recent[0]], weeks[recent[1] - 1]
    totals: dict[tuple[str, str | None], Totals] = defaultdict(Totals)
    for r in rows:
        ws = week_start(r.date)
        if first <= ws <= last:
            totals[(r.page, r.query if by_query else None)].add(r.clicks, r.impressions, r.position)
    target = curve.get(cfg.opportunity_target_position, DEFAULT_CTR[cfg.opportunity_target_position])
    out = []
    for (page, query), t in totals.items():
        pos = t.position
        if pos is None or t.impressions < cfg.opportunity_min_impressions:
            continue
        if not cfg.opportunity_min_position <= pos <= cfg.opportunity_max_position:
            continue
        extra = max(0.0, t.impressions * (target - t.ctr))
        out.append(Opportunity(page, query, t.impressions, t.clicks, pos, t.ctr, target, extra))
    return sorted(out, key=lambda o: (-o.extra_clicks, o.position, o.page))
