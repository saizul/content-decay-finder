"""Self-contained HTML report with inline SVG sparklines (no scripts, no external resources)."""

from __future__ import annotations

from html import escape

from content_decay_finder._version import __version__
from content_decay_finder.analyze import AnalysisResult
from content_decay_finder.report.format import delta_pos, num, pct, pos
from content_decay_finder.report.sparkline import sparkline

CSS = """
:root { color-scheme: light dark; --fg: #1f2937; --muted: #6b7280; --bg: #ffffff; --line: #e5e7eb;
  --bad: #dc2626; --warn: #d97706; --good: #059669; --card: #f9fafb; }
@media (prefers-color-scheme: dark) { :root { --fg: #e5e7eb; --muted: #9ca3af; --bg: #111827; --line: #374151;
  --card: #1f2937; } }
* { box-sizing: border-box; }
body { font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--fg);
  background: var(--bg); margin: 0 auto; padding: 24px; max-width: 1280px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 32px 0 8px; }
.muted { color: var(--muted); } .note { border-left: 3px solid var(--warn); padding: 4px 10px; margin: 8px 0;
  background: var(--card); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 16px 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
.card b { display: block; font-size: 20px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
th { font-weight: 600; color: var(--muted); white-space: nowrap; } td.n { text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
td.url { max-width: 420px; overflow-wrap: anywhere; }
.badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.decaying { background: #fee2e2; color: #991b1b; } .watch { background: #fef3c7; color: #92400e; }
.growing { background: #d1fae5; color: #065f46; } .stable, .new, .low-data { background: var(--card);
  color: var(--muted); }
.bar { height: 6px; background: var(--bad); border-radius: 3px; }
.neg { color: var(--bad); } .pos { color: var(--good); }
footer { margin-top: 40px; font-size: 12px; color: var(--muted); }
"""


def _cls(value: float | None) -> str:
    if value is None:
        return ""
    return "neg" if value < 0 else "pos" if value > 0 else ""


def render_html(result: AnalysisResult) -> str:
    cfg = result.config
    site = result.site
    e = escape
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="robots" content="noindex">',
        f"<title>Content decay report {e(str(result.first_date))} to {e(str(result.last_date))}</title>",
        f"<style>{CSS}</style></head><body>",
        "<h1>Content decay report</h1>",
        f'<p class="muted">Data from {e(str(result.first_date))} to {e(str(result.last_date))} '
        f"({len(result.weeks)} full weeks). Baseline {e(result.windows['baseline'])}, "
        f"recent {e(result.windows['recent'])}, trend over {e(result.windows['trend'])}.</p>",
    ]
    for note in result.notes:
        parts.append(f'<p class="note">{e(note)}</p>')
    parts.append('<div class="cards">')
    parts.append(
        f'<div class="card">Clicks per week<b>{num(site.recent_clicks)}</b>'
        f'<span class="{_cls(site.clicks_change)}">{pct(site.clicks_change)}</span> vs baseline'
        f"{sparkline(site.weekly_clicks, 150, 30, label='site clicks per week')}</div>"
    )
    parts.append(
        f'<div class="card">After seasonality<b class="{_cls(site.adjusted_change)}">{pct(site.adjusted_change)}</b>'
        f"factor {site.seasonal_factor:.2f} ({e(site.seasonal_source)})</div>"
    )
    for status in ("decaying", "watch", "growing"):
        parts.append(
            f'<div class="card">{status.capitalize()} pages<b>{site.status_counts.get(status, 0)}</b>'
            f"of {site.pages}</div>"
        )
    parts.append(f'<div class="card">Clicks lost (recent window)<b>{num(site.lost_clicks)}</b>on flagged pages</div>')
    parts.append("</div>")

    parts.append("<h2>Refresh priorities</h2>")
    ranked = result.ranked()[: cfg.top]
    if not ranked:
        parts.append("<p>No decaying pages found.</p>")
    else:
        parts.append(
            "<table><thead><tr><th>#</th><th>Page</th><th>Status</th><th>Priority</th><th>Clicks/week</th>"
            "<th>Lost clicks</th><th>Change (adj.)</th><th>Impressions</th><th>Position</th><th>Position trend</th>"
            "<th>Causes</th></tr></thead><tbody>"
        )
        for i, p in enumerate(ranked, 1):
            parts.append(
                f"<tr><td class='n'>{i}</td><td class='url'><a href=\"{e(p.page)}\" rel=\"noopener noreferrer\">"
                f"{e(p.page)}</a><br><span class='muted'>{e(p.section)}</span></td>"
                f"<td><span class='badge {e(p.status)}'>{e(p.status)}</span></td>"
                f"<td class='n'>{p.priority:.0f}<div class='bar' style='width:{max(2, p.priority):.0f}%'></div></td>"
                f"<td>{sparkline(p.weekly_clicks, label='clicks per week')}<br>"
                f"<span class='muted'>{num(p.baseline_clicks, 1)} → {num(p.recent_clicks, 1)}</span></td>"
                f"<td class='n'>{num(p.lost_clicks)}</td>"
                f"<td class='n {_cls(p.adjusted_change)}'>{pct(p.adjusted_change)}</td>"
                f"<td>{sparkline(p.weekly_impressions, stroke='#7c3aed', label='impressions per week')}</td>"
                f"<td class='n'>{pos(p.baseline_position)} → {pos(p.recent_position)}<br>"
                f"<span class='muted'>{delta_pos(p.position_change)}</span></td>"
                f"<td>{sparkline(p.weekly_position, stroke='#d97706', invert=True, label='average position')}</td>"
                f"<td>{e(', '.join(p.causes) or '-')}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append("<h2>Sections</h2>")
    parts.append(
        "<table><thead><tr><th>Section</th><th>Pages</th><th>Decaying</th><th>Watch</th><th>Growing</th>"
        "<th>Clicks/week</th><th>Trend</th><th>Change (adj.)</th><th>Lost clicks</th></tr></thead><tbody>"
    )
    for s in result.sections[: cfg.top]:
        parts.append(
            f"<tr><td class='url'>{e(s.section)}</td><td class='n'>{s.pages}</td><td class='n'>{s.decaying}</td>"
            f"<td class='n'>{s.watch}</td><td class='n'>{s.growing}</td>"
            f"<td class='n'>{num(s.baseline_clicks, 1)} → {num(s.recent_clicks, 1)}</td>"
            f"<td>{sparkline(s.weekly_clicks, label='section clicks per week')}</td>"
            f"<td class='n {_cls(s.adjusted_change)}'>{pct(s.adjusted_change)}</td>"
            f"<td class='n'>{num(s.lost_clicks)}</td></tr>"
        )
    parts.append("</tbody></table>")

    parts.append("<h2>Cannibalisation</h2>")
    if not result.cannibalization:
        text = "No query moves between pages." if result.has_queries else "No query-level data."
        parts.append(f"<p>{text}</p>")
    else:
        parts.append(
            "<table><thead><tr><th>Query</th><th>Impressions</th><th>Switches</th><th>Leader before → now</th>"
            "<th>Competing pages (share, position, weeks leading)</th></tr></thead><tbody>"
        )
        for c in result.cannibalization[: cfg.top]:
            pages = "<br>".join(
                f"{e(p.page)} <span class='muted'>({pct(p.share, False)}, {pos(p.position)}, {p.weeks_leading})</span>"
                for p in c.pages
            )
            parts.append(
                f"<tr><td>{e(c.query)}</td><td class='n'>{num(c.impressions)}</td><td class='n'>{c.switches}</td>"
                f"<td class='url'>{e(c.baseline_leader or '-')}<br>→ {e(c.recent_leader or '-')}</td>"
                f"<td class='url'>{pages}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append(
        f"<h2>Almost page 1 (positions {cfg.opportunity_min_position:g} to {cfg.opportunity_max_position:g})</h2>"
    )
    combined = sorted(result.opportunities + result.query_opportunities, key=lambda o: -o.extra_clicks)[: cfg.top]
    if not combined:
        parts.append("<p>No pages in that range with enough impressions.</p>")
    else:
        parts.append(
            f"<p class='muted'>Estimated extra clicks in the recent window at position "
            f"{cfg.opportunity_target_position} (CTR {pct(result.ctr_curve[cfg.opportunity_target_position], False)}"
            ", from this site's own data where it has enough impressions).</p>"
        )
        parts.append(
            "<table><thead><tr><th>Page</th><th>Query</th><th>Impressions</th><th>Position</th><th>CTR</th>"
            "<th>Est. extra clicks</th></tr></thead><tbody>"
        )
        for o in combined:
            parts.append(
                f"<tr><td class='url'>{e(o.page)}</td><td>{e(o.query or '(all queries)')}</td>"
                f"<td class='n'>{num(o.impressions)}</td><td class='n'>{pos(o.position)}</td>"
                f"<td class='n'>{pct(o.ctr, False)}</td><td class='n'>{num(o.extra_clicks)}</td></tr>"
            )
        parts.append("</tbody></table>")
    parts.append(
        f"<footer>Report made with content-decay-finder {e(__version__)}. Priority = lost clicks × trend steepness "
        "× current impressions, scaled to 0-100.</footer></body></html>"
    )
    return "\n".join(parts) + "\n"
