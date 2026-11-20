"""Compare two JSON reports: which pages started decaying, got worse, improved or recovered."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_decay_finder.report.format import num, pct

#: Status severity for "worse" / "better" decisions between two runs.
_RANK = {"watch": 1, "decaying": 2}


class CompareError(ValueError):
    pass


@dataclass(frozen=True)
class PageChange:
    page: str
    kind: str  # new, worse, better, resolved, unchanged
    old_status: str | None
    new_status: str | None
    old_priority: float | None
    new_priority: float | None
    lost_clicks: float | None

    @property
    def priority_change(self) -> float | None:
        if self.old_priority is None or self.new_priority is None:
            return None
        return round(self.new_priority - self.old_priority, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "change": self.kind,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "old_priority": self.old_priority,
            "new_priority": self.new_priority,
            "priority_change": self.priority_change,
            "lost_clicks": self.lost_clicks,
        }


@dataclass
class Comparison:
    old_period: str
    new_period: str
    old_site: dict[str, Any]
    new_site: dict[str, Any]
    changes: list[PageChange] = field(default_factory=list)
    new_truncated: bool = False

    def of_kind(self, kind: str) -> list[PageChange]:
        return [c for c in self.changes if c.kind == kind]

    @property
    def regressions(self) -> list[PageChange]:
        """Pages that are newly flagged or moved from watch to decaying."""
        return self.of_kind("new") + self.of_kind("worse")

    def to_dict(self) -> dict[str, Any]:
        keys = ("new", "worse", "better", "resolved", "unchanged")
        return {
            "tool": "content-decay-finder",
            "comparison": {"old": self.old_period, "new": self.new_period},
            "site": {
                "old_adjusted_change": self.old_site.get("adjusted_change"),
                "new_adjusted_change": self.new_site.get("adjusted_change"),
                "old_lost_clicks": self.old_site.get("lost_clicks"),
                "new_lost_clicks": self.new_site.get("lost_clicks"),
                "old_status_counts": self.old_site.get("status_counts", {}),
                "new_status_counts": self.new_site.get("status_counts", {}),
            },
            "counts": {k: len(self.of_kind(k)) for k in keys},
            "pages": {k: [c.to_dict() for c in self.of_kind(k)] for k in keys},
        }


def load_report(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CompareError(f"{path}: no such file") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompareError(f"{path}: not a JSON file ({exc})") from exc
    if not isinstance(data, dict) or data.get("tool") != "content-decay-finder" or "refresh_priorities" not in data:
        raise CompareError(f"{path}: not a content-decay-finder JSON report (create one with -f json)")
    if not isinstance(data["refresh_priorities"], list):
        raise CompareError(f"{path}: refresh_priorities must be a list")
    return data


def _period(report: dict[str, Any]) -> str:
    d = report.get("data") or {}
    return f"{d.get('first_date', '?')} to {d.get('last_date', '?')}"


def _flagged(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in report["refresh_priorities"]:
        if isinstance(item, dict) and isinstance(item.get("page"), str) and item.get("status") in _RANK:
            out.setdefault(item["page"], item)
    return out


def compare_reports(old: dict[str, Any], new: dict[str, Any]) -> Comparison:
    """Compare the flagged (decaying and watch) pages of two reports."""
    old_pages, new_pages = _flagged(old), _flagged(new)
    changes: list[PageChange] = []
    for page, item in new_pages.items():
        before = old_pages.get(page)
        status = item["status"]
        if before is None:
            kind = "new"
        elif _RANK[status] > _RANK[before["status"]]:
            kind = "worse"
        elif _RANK[status] < _RANK[before["status"]]:
            kind = "better"
        else:
            kind = "unchanged"
        changes.append(
            PageChange(
                page,
                kind,
                before["status"] if before else None,
                status,
                before.get("priority") if before else None,
                item.get("priority"),
                item.get("lost_clicks"),
            )
        )
    for page, item in old_pages.items():
        if page not in new_pages:
            changes.append(
                PageChange(page, "resolved", item["status"], None, item.get("priority"), None, item.get("lost_clicks"))
            )
    changes.sort(key=lambda c: (-(c.new_priority or c.old_priority or 0.0), c.page))
    # A report holds at most --top flagged pages; if the new one is full, "resolved" may only mean "ranked lower".
    top = (new.get("settings") or {}).get("top")
    truncated = isinstance(top, int) and len(new["refresh_priorities"]) >= top
    return Comparison(_period(old), _period(new), old.get("site") or {}, new.get("site") or {}, changes, truncated)


_LABELS = {
    "new": "Newly flagged",
    "worse": "Worse (watch -> decaying)",
    "better": "Better (decaying -> watch)",
    "resolved": "No longer flagged",
}


def _line(c: PageChange) -> str:
    if c.kind == "resolved":
        return f"{c.page}  (was {c.old_status}, priority {num(c.old_priority, 1)})"
    delta = c.priority_change
    change = f", {delta:+.1f}" if delta is not None else ""
    return f"{c.page}  ({c.new_status}, priority {num(c.new_priority, 1)}{change}, lost {num(c.lost_clicks)} clicks)"


def render_text(cmp: Comparison) -> str:
    lines = [
        f"old: {cmp.old_period}",
        f"new: {cmp.new_period}",
        f"site clicks after seasonality: {pct(cmp.old_site.get('adjusted_change'))} -> "
        f"{pct(cmp.new_site.get('adjusted_change'))}, lost clicks {num(cmp.old_site.get('lost_clicks'))} -> "
        f"{num(cmp.new_site.get('lost_clicks'))}",
    ]
    counts = ", ".join(f"{len(cmp.of_kind(k))} {k}" for k in ("new", "worse", "better", "resolved", "unchanged"))
    lines.append(f"pages: {counts}")
    for kind, label in _LABELS.items():
        items = cmp.of_kind(kind)
        if items:
            lines.append("")
            lines.append(f"{label}:")
            lines.extend(f"  {_line(c)}" for c in items)
    if cmp.new_truncated and cmp.of_kind("resolved"):
        lines.append("")
        lines.append("note: the new report's list is full (--top); 'no longer flagged' pages may only rank lower")
    return "\n".join(lines) + "\n"


def render_markdown(cmp: Comparison) -> str:
    out = [
        "# Content decay: changes since the last report",
        "",
        f"Old report: {cmp.old_period}  ",
        f"New report: {cmp.new_period}",
        "",
        "| | Old | New |",
        "| --- | ---: | ---: |",
        f"| Site clicks after seasonality | {pct(cmp.old_site.get('adjusted_change'))} | "
        f"{pct(cmp.new_site.get('adjusted_change'))} |",
        f"| Lost clicks | {num(cmp.old_site.get('lost_clicks'))} | {num(cmp.new_site.get('lost_clicks'))} |",
    ]
    for kind, label in _LABELS.items():
        items = cmp.of_kind(kind)
        if not items:
            continue
        out += [
            "",
            f"## {label} ({len(items)})",
            "",
            "| Page | Status | Priority | Lost clicks |",
            "| --- | --- | ---: | ---: |",
        ]
        for c in items:
            status = c.new_status or f"was {c.old_status}"
            if c.old_status and c.new_status and c.old_status != c.new_status:
                status = f"{c.old_status} -> {c.new_status}"
            priority = num(c.new_priority if c.new_priority is not None else c.old_priority, 1)
            out.append(f"| {c.page.replace('|', '%7C')} | {status} | {priority} | {num(c.lost_clicks)} |")
    if not any(cmp.of_kind(k) for k in _LABELS):
        out += ["", "No pages changed status."]
    return "\n".join(out) + "\n"


def render_json(cmp: Comparison) -> str:
    return json.dumps(cmp.to_dict(), indent=2, ensure_ascii=False) + "\n"


RENDERERS = {"text": render_text, "markdown": render_markdown, "json": render_json}
