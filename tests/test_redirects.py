import io
import json
import re
from datetime import date
from pathlib import Path

import pytest

from content_decay_finder import AnalysisConfig, analyze
from content_decay_finder.cli import main
from content_decay_finder.config import ConfigError, load_config_file
from content_decay_finder.loader import Dataset, write_csv
from content_decay_finder.model import Row
from content_decay_finder.redirects import RedirectError, RedirectMap, iter_redirect_pairs, load_redirects
from content_decay_finder.report import render_html, render_markdown, write_csv_reports
from synth import daily_rows, page, steady

WEEKS = 30
MOVE_WEEK = 22  # /old-guide/ was redirected to /new-guide/ at the start of this week


def migrated_dataset() -> Dataset:
    """A guide that moved URL: same traffic, old URL until MOVE_WEEK, new URL after."""
    ds = Dataset(sources=["synthetic"])
    ds.page_rows += daily_rows(page("/old-guide/"), steady(50, 1000, 3.0), MOVE_WEEK)
    ds.page_rows += daily_rows(page("/new-guide/"), steady(50, 1000, 3.0), WEEKS, first_week=MOVE_WEEK)
    ds.page_rows += daily_rows(page("/products/widget"), steady(40, 800, 4.0), WEEKS)
    ds.query_rows += daily_rows(page("/old-guide/"), steady(10, 200, 3.0), MOVE_WEEK, query="widget guide")
    ds.query_rows += daily_rows(
        page("/new-guide/"), steady(10, 200, 3.0), WEEKS, query="widget guide", first_week=MOVE_WEEK
    )
    return ds.finalize()


def by_page(result) -> dict:
    return {p.page: p for p in result.pages}


# --- RedirectMap --------------------------------------------------------------------------------------------------


def test_resolve_follows_chains_and_paths():
    rmap = RedirectMap()
    rmap.add("https://www.example.com/a", "https://www.example.com/b")
    rmap.add("/b", "/c/")
    rmap.add("HTTPS://WWW.EXAMPLE.COM/c/#top", "https://www.example.com/final/")
    assert rmap.resolve("https://www.example.com/a") == "https://www.example.com/final/"
    # a path rule keeps the host of the URL being redirected
    assert rmap.resolve("https://shop.example.com/b") == "https://shop.example.com/c/"
    assert rmap.resolve("https://www.example.com/untouched") == "https://www.example.com/untouched"


def test_query_strings_follow_the_strip_setting():
    stripped = RedirectMap()
    stripped.add("https://e.example/p?id=1", "https://e.example/new")
    assert stripped.resolve("https://e.example/p") == "https://e.example/new"
    kept = RedirectMap(strip_query=False)
    kept.add("https://e.example/p?id=1", "https://e.example/new")
    assert kept.resolve("https://e.example/p?id=1") == "https://e.example/new"
    assert kept.resolve("https://e.example/p?id=2") == "https://e.example/p?id=2"


def test_self_redirects_are_ignored():
    rmap = RedirectMap()
    rmap.add("https://e.example/x/", "HTTPS://E.EXAMPLE/x/")
    assert len(rmap) == 0 and not rmap


@pytest.mark.parametrize(
    ("pairs", "message"),
    [
        ([("/a", "/b"), ("/b", "/a")], "redirect loop"),
        ([("/a", "/b"), ("/b", "/c"), ("/c", "/a")], "/a -> /b -> /c -> /a"),
        ([("/a", "/b"), ("/a", "/c")], "conflicting"),
        ([("old-page", "/b")], "paths starting with '/'"),
        ([("ftp://e.example/a", "/b")], "http(s) URLs"),
    ],
)
def test_bad_maps_are_rejected(pairs, message):
    rmap = RedirectMap()
    with pytest.raises(RedirectError, match=message.replace("(", r"\(").replace(")", r"\)")):
        rmap.update(pairs)
        rmap.validate()


def test_overlong_chain_is_rejected():
    rmap = RedirectMap()
    rmap.update((f"/p{i}", f"/p{i + 1}") for i in range(25))
    with pytest.raises(RedirectError, match="longer than 20 hops"):
        rmap.validate()


def test_apply_rewrites_rows_and_reports_merges():
    rmap = RedirectMap()
    rmap.add("/old", "/new")
    rows = [
        Row(date(2026, 1, 5), "https://e.example/old", 3, 30, 2.0),
        Row(date(2026, 1, 5), "https://e.example/new", 1, 10, 4.0),
        Row(date(2026, 1, 5), "https://e.example/other", 1, 10, 4.0),
    ]
    out, merged = rmap.apply(rows)
    assert [r.page for r in out] == ["https://e.example/new", "https://e.example/new", "https://e.example/other"]
    assert merged == {"https://e.example/new": {"https://e.example/old"}}
    assert out[0].clicks == 3 and out[0].position == 2.0


# --- CSV parsing --------------------------------------------------------------------------------------------------


def test_csv_without_header():
    pairs = list(iter_redirect_pairs("/a,/b\n# a comment\n\nhttps://e.example/c,https://e.example/d\n"))
    assert pairs == [("/a", "/b", True), ("https://e.example/c", "https://e.example/d", True)]


def test_screaming_frog_style_export_skips_non_redirects():
    text = (
        '"Address","Status Code","Redirect URL"\n'
        '"https://e.example/old","301","https://e.example/new"\n'
        '"https://e.example/gone","404",""\n'
        '"https://e.example/canonical","200","https://e.example/elsewhere"\n'
    )
    assert list(iter_redirect_pairs(text)) == [
        ("https://e.example/old", "https://e.example/new", True),
        ("https://e.example/canonical", "https://e.example/elsewhere", False),
    ]


def test_semicolon_csv_with_bom(tmp_path: Path):
    path = tmp_path / "r.csv"
    path.write_text("﻿Source URL;Target URL;Type\n/old/;/new/;301\n", encoding="utf-8")
    rmap = load_redirects([path])
    assert rmap.rules == {"/old/": "/new/"} and rmap.sources == [str(path)]


def test_csv_errors(tmp_path: Path):
    with pytest.raises(RedirectError, match="not found"):
        load_redirects([tmp_path / "missing.csv"])
    bad = tmp_path / "bad.csv"
    bad.write_text("page,clicks\n/a,3\n")
    with pytest.raises(RedirectError, match="'from' and a 'to' column"):
        load_redirects([bad])
    loop = tmp_path / "loop.csv"
    loop.write_text("from,to\n/a,/b\n/b,/a\n")
    with pytest.raises(RedirectError, match="redirect loop"):
        load_redirects([loop])


# --- analysis -----------------------------------------------------------------------------------------------------


def test_without_a_map_a_moved_page_looks_decaying():
    pages = by_page(analyze(migrated_dataset()))
    assert pages[page("/old-guide/")].status == "decaying"
    assert pages[page("/new-guide/")].status == "new"


def test_map_merges_the_history_into_the_target():
    cfg = AnalysisConfig(redirect_pairs=[("/old-guide/", "/new-guide/")])
    result = analyze(migrated_dataset(), cfg)
    pages = by_page(result)
    assert page("/old-guide/") not in pages
    new = pages[page("/new-guide/")]
    assert new.status == "stable"
    assert new.merged_from == [page("/old-guide/")]
    assert new.baseline_clicks == pytest.approx(350) and new.recent_clicks == pytest.approx(350)
    assert result.decaying == []
    assert any("Redirect map: 1 old URL(s) were merged into 1 page(s)" in n for n in result.notes)
    data = result.to_dict()
    assert data["data"]["redirects"] == {
        "rules": 1,
        "sources": ["config"],
        "skipped_rows": 0,
        "merged_urls": 1,
        "target_pages": 1,
    }
    assert data["refresh_priorities"] == []  # nothing left to refresh


def test_ignore_patterns_match_the_target_url():
    cfg = AnalysisConfig(redirect_pairs=[("/old-guide/", "/new-guide/")])
    cfg.ignore_patterns = [re.compile("/new-guide/")]
    pages = by_page(analyze(migrated_dataset(), cfg))
    assert set(pages) == {page("/products/widget")}


def test_reports_list_merged_urls(tmp_path: Path):
    ds = migrated_dataset()
    # make the merged page decay so it shows up in the refresh table
    ds.page_rows = [
        Row(r.date, r.page, r.clicks * 0.3, r.impressions, r.position) if r.page.endswith("/new-guide/") else r
        for r in ds.page_rows
    ]
    result = analyze(ds, AnalysisConfig(redirect_pairs=[("/old-guide/", "/new-guide/")]))
    assert by_page(result)[page("/new-guide/")].status == "decaying"
    assert "incl. https://www.example.com/old-guide/" in render_markdown(result)
    assert "incl. redirected: https://www.example.com/old-guide/" in render_html(result)
    pages_csv = write_csv_reports(result, tmp_path, "r")[0].read_text().splitlines()
    assert pages_csv[0].endswith(",causes,merged_from")
    assert any(line.endswith("https://www.example.com/old-guide/") for line in pages_csv[1:])


def test_no_map_keeps_json_shape():
    data = analyze(migrated_dataset()).to_dict()
    assert data["data"]["redirects"] is None
    assert all(p["merged_from"] == [] for p in data["refresh_priorities"])


# --- configuration and CLI ----------------------------------------------------------------------------------------


def test_config_file_table_and_relative_file(tmp_path: Path):
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "moved.csv").write_text("from,to\n/a/,/b/\n")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(
        '[analysis]\nredirects_file = "maps/moved.csv"\n[analysis.redirects]\n"/old-guide/" = "/new-guide/"\n'
    )
    cfg = load_config_file(cfg_path)
    assert cfg.redirect_files == [tmp_path / "maps" / "moved.csv"]
    assert cfg.redirect_pairs == [("/old-guide/", "/new-guide/")]
    rmap = cfg.redirect_map()
    assert rmap is not None and len(rmap) == 2
    assert rmap.sources == ["config", str(tmp_path / "maps" / "moved.csv")]


@pytest.mark.parametrize(
    "text",
    ['[analysis]\nredirects = "x.csv"\n', "[analysis]\nredirects_file = 3\n", '[analysis.redirects]\n"/a" = 1\n'],
)
def test_config_rejects_bad_redirect_settings(tmp_path: Path, text: str):
    path = tmp_path / "c.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match="redirect"):
        load_config_file(path)


@pytest.fixture
def migrated_dir(tmp_path: Path) -> Path:
    ds = migrated_dataset()
    write_csv(ds.page_rows, tmp_path / "data" / "pages.csv", with_query=False)
    write_csv(ds.query_rows, tmp_path / "data" / "queries.csv", with_query=True)
    return tmp_path / "data"


def run(args) -> tuple[int, str]:
    out = io.StringIO()
    return main(args, out=out), out.getvalue()


def test_cli_redirects_flag(migrated_dir: Path, tmp_path: Path):
    assert run(["analyze", str(migrated_dir), "--fail-on-decay", "1", "--quiet"])[0] == 1
    redirects = tmp_path / "redirects.csv"
    redirects.write_text("Source,Destination\nhttps://www.example.com/old-guide/,/new-guide/\n")
    out_dir = str(tmp_path / "r")
    args = ["analyze", str(migrated_dir), "--redirects", str(redirects), "--fail-on-decay", "1", "-f", "json"]
    code, out = run([*args, "-o", out_dir])
    assert code == 0, out
    assert "note: Redirect map: 1 old URL(s) were merged" in out
    data = json.loads((tmp_path / "r" / "content-decay.json").read_text())
    assert data["data"]["redirects"]["merged_urls"] == 1


def test_cli_redirect_errors(migrated_dir: Path, tmp_path: Path, capsys):
    loop = tmp_path / "loop.csv"
    loop.write_text("/a,/b\n/b,/a\n")
    assert run(["analyze", str(migrated_dir), "--redirects", str(loop)])[0] == 2
    assert "redirect loop" in capsys.readouterr().err
    assert run(["analyze", str(migrated_dir), "--redirects", str(tmp_path / "nope.csv")])[0] == 2
    assert "redirect map not found" in capsys.readouterr().err
