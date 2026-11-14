import csv
import json
from html.parser import HTMLParser
from pathlib import Path

from content_decay_finder import analyze
from content_decay_finder.loader import Dataset
from content_decay_finder.report import render_html, render_json, render_markdown, write_reports
from content_decay_finder.report.csv_report import _safe
from content_decay_finder.report.format import pct
from content_decay_finder.report.markdown import md_escape
from content_decay_finder.report.sparkline import sparkline
from synth import daily_rows, decaying, page


class TagCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, int] = {}
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if tag == "script":
            self.scripts += 1


def test_sparkline_geometry():
    svg = sparkline([1, 2, 3], width=100, height=20)
    assert svg.startswith('<svg class="spark" width="100" height="20"')
    assert 'points="2.0,18.0 50.0,10.0 98.0,2.0"' in svg
    inverted = sparkline([1, 2, 3], width=100, height=20, invert=True)
    assert 'points="2.0,2.0 50.0,10.0 98.0,18.0"' in inverted
    gaps = sparkline([None, 5, None, 5])
    assert "polyline" in gaps
    assert "polyline" not in sparkline([1])
    assert "&lt;b&gt;" in sparkline([1, 2], label="<b>")


def test_json_report(result):
    data = json.loads(render_json(result))
    assert data["tool"] == "content-decay-finder"
    assert data["refresh_priorities"][0]["page"].endswith("/blog/decaying-guide/")
    assert data["refresh_priorities"][0]["priority"] == 100.0
    assert data["cannibalization"][0]["query"] == "best widget"
    assert data["almost_page_one"][0]["page"].endswith("/guides/almost/")
    assert set(data["ctr_curve"]) == {str(i) for i in range(1, 11)}
    assert data["data"]["windows"]["recent"] == "2025-07-07 to 2025-08-03"


def test_markdown_report(result):
    md = render_markdown(result)
    assert md.startswith("# Content decay report")
    assert "## Refresh priorities" in md and "## Cannibalisation" in md and "## Almost page 1" in md
    assert "| 1 | https://www.example.com/blog/decaying-guide/ | decaying | 100 |" in md
    assert "best widget" in md
    assert "> Seasonality was not adjusted" in md


def test_html_report_is_self_contained(result):
    html = render_html(result)
    parser = TagCounter()
    parser.feed(html)
    assert parser.scripts == 0
    assert parser.tags["svg"] >= 10
    assert "http-equiv" not in html and "<link" not in html
    assert "badge decaying" in html
    assert "Report made with content-decay-finder" in html


def test_html_escapes_untrusted_values():
    weeks = 14
    evil = page('/"><script>alert(1)</script>')
    ds = Dataset(page_rows=daily_rows(evil, decaying(weeks, 4), weeks)).finalize()
    html = render_html(analyze(ds))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_csv_reports(result, tmp_path: Path):
    paths = write_reports(result, ["csv"], tmp_path)
    names = sorted(p.name for p in paths)
    assert names == [
        "content-decay-almost-page-one.csv",
        "content-decay-cannibalization.csv",
        "content-decay-pages.csv",
        "content-decay-sections.csv",
    ]
    rows = list(csv.DictReader((tmp_path / "content-decay-pages.csv").open()))
    assert rows[0]["status"] == "decaying" and rows[0]["priority"] == "100.0"
    assert len(rows) == len(result.pages)
    new = next(r for r in rows if r["page"].endswith("/new-page"))
    assert new["clicks_change"] == ""  # infinite change is left empty


def test_write_all_formats(result, tmp_path: Path):
    paths = write_reports(result, ["json", "markdown", "html"], tmp_path / "out", basename="site")
    assert sorted(p.name for p in paths) == ["site.html", "site.json", "site.md"]


def test_helpers():
    assert _safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _safe("plain") == "plain" and _safe(3) == 3
    assert md_escape("a|b`c") == "a\\|b\\`c"
    assert pct(None) == "n/a" and pct(float("inf")) == "new" and pct(-0.0001) == "0%" and pct(0.25) == "+25%"
