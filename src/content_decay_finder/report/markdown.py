"""Markdown report (GitHub-flavoured tables)."""

from __future__ import annotations

from content_decay_finder.analyze import AnalysisResult
from content_decay_finder.report.format import delta_pos, num, pct, pos

STATUS_ORDER = ("decaying", "watch", "stable", "growing", "new", "low-data")


def md_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("`", "\\`")


def render_markdown(result: AnalysisResult) -> str:
    cfg = result.config
    site = result.site
    out: list[str] = []
    out.append("# Content decay report")
    out.append("")
    out.append(
        f"Data from {result.first_date} to {result.last_date} ({len(result.weeks)} full weeks). "
        f"Baseline: {result.windows['baseline']}. Recent: {result.windows['recent']}."
    )
    out.append("")
    counts = ", ".join(f"{site.status_counts.get(s, 0)} {s}" for s in STATUS_ORDER if site.status_counts.get(s))
    out.append(
        f"**Site**: {num(site.recent_clicks)} clicks/week now vs {num(site.baseline_clicks)} in the baseline "
        f"({pct(site.clicks_change)}, {pct(site.adjusted_change)} after seasonality). "
        f"{site.pages} pages: {counts}. Clicks lost on flagged pages in the recent window: {num(site.lost_clicks)}."
    )
    for note in result.notes:
        out += ["", f"> {note}"]
    out += ["", "## Refresh priorities", ""]
    ranked = result.ranked()[: cfg.top]
    if not ranked:
        out.append("No decaying pages found.")
    else:
        out.append("| # | Page | Status | Priority | Lost clicks | Clicks/wk | Change (adj.) | Position | Causes |")
        out.append("|---:|---|---|---:|---:|---:|---:|---:|---|")
        for i, p in enumerate(ranked, 1):
            out.append(
                f"| {i} | {md_escape(p.page)} | {p.status} | {p.priority:.0f} | {num(p.lost_clicks)} | "
                f"{num(p.baseline_clicks, 1)} → {num(p.recent_clicks, 1)} | {pct(p.adjusted_change)} | "
                f"{pos(p.baseline_position)} → {pos(p.recent_position)} ({delta_pos(p.position_change)}) | "
                f"{', '.join(p.causes) or '-'} |"
            )
    out += ["", "## Sections", ""]
    out.append("| Section | Pages | Decaying | Watch | Growing | Clicks/wk | Change (adj.) | Lost clicks |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in result.sections[: cfg.top]:
        out.append(
            f"| {md_escape(s.section)} | {s.pages} | {s.decaying} | {s.watch} | {s.growing} | "
            f"{num(s.baseline_clicks, 1)} → {num(s.recent_clicks, 1)} | {pct(s.adjusted_change)} | "
            f"{num(s.lost_clicks)} |"
        )
    out += ["", "## Cannibalisation", ""]
    if not result.cannibalization:
        out.append("No query moves between pages." if result.has_queries else "No query-level data.")
    else:
        out.append("| Query | Impressions | Switches | Leader before → now | Pages (share, position) |")
        out.append("|---|---:|---:|---|---|")
        for c in result.cannibalization[: cfg.top]:
            pages = "<br>".join(f"{md_escape(p.page)} ({pct(p.share, False)}, {pos(p.position)})" for p in c.pages)
            out.append(
                f"| {md_escape(c.query)} | {num(c.impressions)} | {c.switches} | "
                f"{md_escape(c.baseline_leader or '-')} → {md_escape(c.recent_leader or '-')} | {pages} |"
            )
    out += ["", f"## Almost page 1 (positions {cfg.opportunity_min_position:g}-{cfg.opportunity_max_position:g})", ""]
    if not result.opportunities and not result.query_opportunities:
        out.append("No pages in that range with enough impressions.")
    else:
        out.append(
            f"Extra clicks are an estimate for the recent window at position {cfg.opportunity_target_position}"
            f" (CTR {pct(result.ctr_curve[cfg.opportunity_target_position], False)})."
        )
        out.append("")
        out.append("| Page | Query | Impressions | Position | CTR | Est. extra clicks |")
        out.append("|---|---|---:|---:|---:|---:|")
        combined = sorted(result.opportunities + result.query_opportunities, key=lambda o: -o.extra_clicks)
        for o in combined[: cfg.top]:
            out.append(
                f"| {md_escape(o.page)} | {md_escape(o.query or '(all)')} | {num(o.impressions)} | "
                f"{pos(o.position)} | {pct(o.ctr, False)} | {num(o.extra_clicks)} |"
            )
    out.append("")
    return "\n".join(out)
