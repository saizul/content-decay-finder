"""Report writers: CSV, JSON, Markdown and HTML (with inline SVG sparklines)."""

from __future__ import annotations

from pathlib import Path

from content_decay_finder.analyze import AnalysisResult
from content_decay_finder.report.csv_report import write_csv_reports
from content_decay_finder.report.html import render_html
from content_decay_finder.report.json_report import render_json
from content_decay_finder.report.markdown import render_markdown

FORMATS = ("csv", "json", "markdown", "html")
EXTENSIONS = {"json": ".json", "markdown": ".md", "html": ".html"}

__all__ = [
    "EXTENSIONS",
    "FORMATS",
    "render_html",
    "render_json",
    "render_markdown",
    "write_csv_reports",
    "write_reports",
]


def write_reports(
    result: AnalysisResult, formats: list[str], out_dir: Path, basename: str = "content-decay"
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fmt in formats:
        if fmt == "csv":
            written += write_csv_reports(result, out_dir, basename)
            continue
        path = out_dir / f"{basename}{EXTENSIONS[fmt]}"
        renderer = {"json": render_json, "markdown": render_markdown, "html": render_html}[fmt]
        path.write_text(renderer(result), encoding="utf-8")
        written.append(path)
    return written
