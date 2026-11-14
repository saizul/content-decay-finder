import io
import json
from datetime import date
from pathlib import Path

import pytest

from content_decay_finder.cli import main
from content_decay_finder.loader import write_csv
from fake_api import FakeGoogle
from synth import standard_dataset


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    ds = standard_dataset()
    write_csv(ds.page_rows, tmp_path / "data" / "pages.csv", with_query=False)
    write_csv(ds.query_rows, tmp_path / "data" / "queries.csv", with_query=True)
    return tmp_path / "data"


def run(args, **kwargs) -> tuple[int, str]:
    out = io.StringIO()
    return main(args, out=out, **kwargs), out.getvalue()


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "content-decay-finder 0.1.0" in capsys.readouterr().out


def test_analyze_csv_writes_reports(data_dir: Path, tmp_path: Path):
    out_dir = tmp_path / "report"
    code, out = run(["analyze", str(data_dir), "-f", "all", "-o", str(out_dir)])
    assert code == 0, out
    assert "refresh first:" in out and "decaying-guide" in out
    assert "cannibalised queries: 1" in out
    assert {p.name for p in out_dir.iterdir()} >= {
        "content-decay.html",
        "content-decay.json",
        "content-decay.md",
        "content-decay-pages.csv",
    }


def test_flags_override_config(data_dir: Path, tmp_path: Path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[analysis]\nrecent_weeks = 3\n")
    code, out = run(
        [
            "analyze",
            str(data_dir),
            "--config",
            str(cfg),
            "--recent-weeks",
            "4",
            "-f",
            "json",
            "-o",
            str(tmp_path / "r"),
            "--section",
            "Blog=^/blog/",
            "--quiet",
            "--decline-threshold",
            "0.05",
        ]
    )
    assert code == 0 and out.startswith("wrote")
    data = json.loads((tmp_path / "r" / "content-decay.json").read_text())
    assert data["settings"]["recent_weeks"] == 4
    assert data["settings"]["decline_threshold"] == 0.05
    assert any(s["section"] == "Blog" for s in data["sections"])


def test_fail_on_decay(data_dir: Path):
    assert run(["analyze", str(data_dir), "--fail-on-decay", "2", "--quiet"])[0] == 1
    assert run(["analyze", str(data_dir), "--fail-on-decay", "3", "--quiet"])[0] == 0


@pytest.mark.parametrize(
    "args",
    [
        ["analyze"],
        ["analyze", "missing-dir-xyz.csv"],
        ["analyze", "x.csv", "--site-url", "sc-domain:e.example", "--access-token-env", "T"],
        ["analyze", "-f", "pdf", "x.csv"],
        ["analyze", "x.csv", "--section", "broken"],
        ["analyze", "x.csv", "--ignore", "("],
    ],
)
def test_usage_errors(args, capsys):
    assert run(args)[0] == 2
    assert "error:" in capsys.readouterr().err


def test_fetch_and_analyze_via_api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GSC_TOKEN", "static")
    fake = FakeGoogle(pages=2, rows_per_day=1)
    code, out = run(
        [
            "fetch",
            "--site-url",
            "sc-domain:example.com",
            "--access-token-env",
            "GSC_TOKEN",
            "--start",
            "2026-01-05",
            "--end",
            "2026-04-05",
            "--chunk-days",
            "30",
            "-o",
            str(tmp_path / "gsc"),
        ],
        transport=fake,
    )
    assert code == 0, out
    pages = (tmp_path / "gsc" / "pages.csv").read_text().splitlines()
    assert pages[0] == "date,page,clicks,impressions,ctr,position"
    assert len(pages) == 1 + 91 * 2
    assert (tmp_path / "gsc" / "queries.csv").exists()
    assert {tuple(q["dimensions"]) for q in fake.queries} == {("date", "page"), ("date", "page", "query")}

    fake2 = FakeGoogle(pages=2, rows_per_day=1)
    code, out = run(
        [
            "analyze",
            "--site-url",
            "sc-domain:example.com",
            "--access-token-env",
            "GSC_TOKEN",
            "--no-queries",
            "--save-csv",
            str(tmp_path / "saved"),
            "--filter",
            "page~/p",
        ],
        transport=fake2,
        today=date(2026, 11, 14),
    )
    assert code == 0, out
    assert (tmp_path / "saved" / "pages.csv").exists() and not (tmp_path / "saved" / "queries.csv").exists()
    assert fake2.queries[0]["dimensionFilterGroups"][0]["filters"][0]["operator"] == "contains"
    assert fake2.queries[-1]["endDate"] == "2026-11-11"


def test_fetch_needs_site_url(capsys):
    assert run(["fetch"])[0] == 2
