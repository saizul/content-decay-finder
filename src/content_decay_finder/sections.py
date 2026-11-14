"""Rolling page results up to URL sections."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from content_decay_finder.decay import PageResult
from content_decay_finder.stats import pct_change


@dataclass
class SectionResult:
    section: str
    pages: int = 0
    decaying: int = 0
    watch: int = 0
    growing: int = 0
    baseline_clicks: float = 0.0
    recent_clicks: float = 0.0
    expected_clicks: float = 0.0
    lost_clicks: float = 0.0
    priority_raw: float = 0.0
    top_pages: list[str] = field(default_factory=list)
    weekly_clicks: list[float] = field(default_factory=list)

    @property
    def clicks_change(self) -> float | None:
        return pct_change(self.baseline_clicks, self.recent_clicks)

    @property
    def adjusted_change(self) -> float | None:
        return pct_change(self.expected_clicks, self.recent_clicks)

    @property
    def decay_share(self) -> float:
        return self.decaying / self.pages if self.pages else 0.0

    def to_dict(self) -> dict[str, object]:
        def r(v: float | None, d: int = 4) -> float | None:
            return None if v is None or v in (float("inf"),) else round(v, d)

        return {
            "section": self.section,
            "pages": self.pages,
            "decaying": self.decaying,
            "watch": self.watch,
            "growing": self.growing,
            "decay_share": r(self.decay_share),
            "baseline_clicks_weekly": r(self.baseline_clicks, 2),
            "recent_clicks_weekly": r(self.recent_clicks, 2),
            "clicks_change": r(self.clicks_change),
            "adjusted_change": r(self.adjusted_change),
            "lost_clicks": r(self.lost_clicks, 1),
            "top_pages": self.top_pages,
            "weekly_clicks": [round(v, 1) for v in self.weekly_clicks],
        }


def summarize_sections(results: list[PageResult], top_pages: int = 5) -> list[SectionResult]:
    groups: dict[str, list[PageResult]] = defaultdict(list)
    for r in results:
        groups[r.section].append(r)
    out = []
    for name, pages in groups.items():
        s = SectionResult(name, pages=len(pages))
        for p in pages:
            s.decaying += p.status == "decaying"
            s.watch += p.status == "watch"
            s.growing += p.status == "growing"
            s.baseline_clicks += p.baseline_clicks
            s.recent_clicks += p.recent_clicks
            s.expected_clicks += p.expected_clicks
            s.lost_clicks += p.lost_clicks if p.status in ("decaying", "watch") else 0.0
            s.priority_raw += p.priority_raw
            if not s.weekly_clicks:
                s.weekly_clicks = [0.0] * len(p.weekly_clicks)
            for i, v in enumerate(p.weekly_clicks):
                s.weekly_clicks[i] += v
        ranked = sorted((p for p in pages if p.priority_raw > 0), key=lambda p: -p.priority_raw)
        s.top_pages = [p.page for p in ranked[:top_pages]]
        out.append(s)
    return sorted(out, key=lambda s: (-s.lost_clicks, s.section))
