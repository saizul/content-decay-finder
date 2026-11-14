"""CSV reports: one file per table, ready for a spreadsheet."""

from __future__ import annotations

import csv
from pathlib import Path

from content_decay_finder.analyze import AnalysisResult


def _safe(value: object) -> object:
    """Neutralise spreadsheet formulas in text cells (CSV injection)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _round(value: float | None, digits: int = 4) -> object:
    if value is None or value == float("inf"):
        return ""
    return round(value, digits)


def _write(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([_safe(v) for v in row])
    return path


def write_csv_reports(result: AnalysisResult, out_dir: Path, basename: str) -> list[Path]:
    pages = [
        [
            p.page,
            p.section,
            p.status,
            _round(p.priority, 1),
            _round(p.priority_raw, 2),
            _round(p.lost_clicks, 1),
            _round(p.steepness),
            _round(p.baseline_clicks, 2),
            _round(p.recent_clicks, 2),
            _round(p.expected_clicks, 2),
            _round(p.clicks_change),
            _round(p.adjusted_change),
            _round(p.baseline_impressions, 1),
            _round(p.recent_impressions, 1),
            _round(p.impressions_change),
            _round(p.baseline_position, 2),
            _round(p.recent_position, 2),
            _round(p.position_change, 2),
            _round(p.baseline_ctr),
            _round(p.recent_ctr),
            _round(p.seasonal.factor, 3),
            p.seasonal.source,
            _round(p.clicks_trend.relative_slope),
            _round(p.clicks_trend.r2, 3),
            ";".join(p.causes),
        ]
        for p in sorted(result.pages, key=lambda p: (-p.priority_raw, -p.lost_clicks, p.page))
    ]
    written = [
        _write(
            out_dir / f"{basename}-pages.csv",
            [
                "page",
                "section",
                "status",
                "priority",
                "priority_raw",
                "lost_clicks",
                "steepness",
                "baseline_clicks_weekly",
                "recent_clicks_weekly",
                "expected_clicks_weekly",
                "clicks_change",
                "adjusted_change",
                "baseline_impressions_weekly",
                "recent_impressions_weekly",
                "impressions_change",
                "baseline_position",
                "recent_position",
                "position_change",
                "baseline_ctr",
                "recent_ctr",
                "seasonal_factor",
                "seasonal_source",
                "clicks_trend_relative_slope",
                "clicks_trend_r2",
                "causes",
            ],
            pages,
        ),
        _write(
            out_dir / f"{basename}-sections.csv",
            [
                "section",
                "pages",
                "decaying",
                "watch",
                "growing",
                "baseline_clicks_weekly",
                "recent_clicks_weekly",
                "clicks_change",
                "adjusted_change",
                "lost_clicks",
            ],
            [
                [
                    s.section,
                    s.pages,
                    s.decaying,
                    s.watch,
                    s.growing,
                    _round(s.baseline_clicks, 2),
                    _round(s.recent_clicks, 2),
                    _round(s.clicks_change),
                    _round(s.adjusted_change),
                    _round(s.lost_clicks, 1),
                ]
                for s in result.sections
            ],
        ),
        _write(
            out_dir / f"{basename}-almost-page-one.csv",
            ["page", "query", "impressions", "clicks", "position", "ctr", "target_ctr", "extra_clicks"],
            [
                [
                    o.page,
                    o.query or "",
                    _round(o.impressions, 1),
                    _round(o.clicks, 1),
                    _round(o.position, 2),
                    _round(o.ctr),
                    _round(o.target_ctr),
                    _round(o.extra_clicks, 1),
                ]
                for o in result.opportunities + result.query_opportunities
            ],
        ),
    ]
    if result.cannibalization:
        rows = []
        for c in result.cannibalization:
            for p in c.pages:
                rows.append(
                    [
                        c.query,
                        _round(c.impressions, 1),
                        c.switches,
                        c.baseline_leader or "",
                        c.recent_leader or "",
                        p.page,
                        _round(p.share),
                        _round(p.position, 2),
                        _round(p.clicks, 1),
                        p.weeks_leading,
                    ]
                )
        written.append(
            _write(
                out_dir / f"{basename}-cannibalization.csv",
                [
                    "query",
                    "query_impressions",
                    "switches",
                    "baseline_leader",
                    "recent_leader",
                    "page",
                    "share",
                    "position",
                    "clicks",
                    "weeks_leading",
                ],
                rows,
            )
        )
    return written
