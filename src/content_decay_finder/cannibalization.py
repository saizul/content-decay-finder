"""Queries whose clicks move between pages of the same site (keyword cannibalisation)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise

from content_decay_finder.config import AnalysisConfig
from content_decay_finder.model import Row, Totals
from content_decay_finder.weekly import week_start


@dataclass
class CompetingPage:
    page: str
    clicks: float
    impressions: float
    share: float  # of the query's impressions
    position: float | None
    weeks_leading: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "clicks": round(self.clicks, 1),
            "impressions": round(self.impressions, 1),
            "share": round(self.share, 4),
            "position": None if self.position is None else round(self.position, 2),
            "weeks_leading": self.weeks_leading,
        }


@dataclass
class CannibalCase:
    query: str
    impressions: float
    clicks: float
    switches: int  # how often the leading page changed from one week to the next
    leaders: list[str]  # leading page per week (weeks without data skipped)
    pages: list[CompetingPage] = field(default_factory=list)
    baseline_leader: str | None = None
    recent_leader: str | None = None

    @property
    def score(self) -> float:
        """Impressions at stake, weighted by how evenly they are split and how unstable the leader is."""
        top_share = self.pages[0].share if self.pages else 1.0
        return self.impressions * (1 - top_share + 0.1) * (1 + self.switches)

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "impressions": round(self.impressions, 1),
            "clicks": round(self.clicks, 1),
            "switches": self.switches,
            "baseline_leader": self.baseline_leader,
            "recent_leader": self.recent_leader,
            "score": round(self.score, 1),
            "pages": [p.to_dict() for p in self.pages],
            "leaders": self.leaders,
        }


def _leader(per_page: dict[str, Totals]) -> str | None:
    if not per_page:
        return None
    page, totals = max(per_page.items(), key=lambda kv: (kv[1].clicks, kv[1].impressions, kv[0]))
    return page if totals.impressions > 0 else None


def find_cannibalization(
    rows: Iterable[Row],
    weeks: list[date],
    baseline: tuple[int, int],
    recent: tuple[int, int],
    cfg: AnalysisConfig,
) -> list[CannibalCase]:
    """Look at the baseline + recent weeks. A query is flagged when at least two pages each get
    ``cannibal_min_share`` of its impressions and the leading page either changed between the baseline and the
    recent window or switched at least ``cannibal_min_switches`` times week to week."""
    if not weeks:
        return []
    first, last = weeks[baseline[0]], weeks[recent[1] - 1]
    index = {w: i for i, w in enumerate(weeks)}
    data: dict[str, dict[int, dict[str, Totals]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        if not row.query:
            continue
        ws = week_start(row.date)
        if ws < first or ws > last or ws not in index:
            continue
        per_page = data[row.query][index[ws]]
        per_page.setdefault(row.page, Totals()).add(row.clicks, row.impressions, row.position)
    cases = []
    for query, by_week in data.items():
        totals: dict[str, Totals] = defaultdict(Totals)
        for per_page in by_week.values():
            for page, t in per_page.items():
                totals[page].merge(t)
        impressions = sum(t.impressions for t in totals.values())
        if impressions < cfg.cannibal_min_impressions or len(totals) < 2:
            continue
        competing = [
            CompetingPage(page, t.clicks, t.impressions, t.impressions / impressions, t.position)
            for page, t in totals.items()
            if t.impressions / impressions >= cfg.cannibal_min_share
        ]
        if len(competing) < 2:
            continue
        leaders = [ld for i in sorted(by_week) if (ld := _leader(by_week[i])) is not None]
        switches = sum(1 for a, b in pairwise(leaders) if a != b)

        def window_leader(span: tuple[int, int], by_week=by_week) -> str | None:
            merged: dict[str, Totals] = defaultdict(Totals)
            for i in range(*span):
                for page, t in by_week.get(i, {}).items():
                    merged[page].merge(t)
            return _leader(merged)

        base_leader, recent_leader = window_leader(baseline), window_leader(recent)
        moved = base_leader is not None and recent_leader is not None and base_leader != recent_leader
        if switches < cfg.cannibal_min_switches and not moved:
            continue
        for c in competing:
            c.weeks_leading = leaders.count(c.page)
        competing.sort(key=lambda c: (-c.impressions, c.page))
        cases.append(
            CannibalCase(
                query=query,
                impressions=impressions,
                clicks=sum(t.clicks for t in totals.values()),
                switches=switches,
                leaders=leaders,
                pages=competing,
                baseline_leader=base_leader,
                recent_leader=recent_leader,
            )
        )
    return sorted(cases, key=lambda c: (-c.score, c.query))
