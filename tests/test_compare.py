import io
import json
from pathlib import Path

import pytest

from content_decay_finder.cli import main
from content_decay_finder.compare import CompareError, compare_reports, load_report, render_markdown, render_text


def page(url, status, priority, lost=100.0):
    return {"page": url, "status": status, "priority": priority, "lost_clicks": lost}


def report(pages, first="2026-01-05", last="2026-06-28", top=50, adjusted=-0.1, lost=500.0):
    return {
        "tool": "content-decay-finder",
        "version": "0.1.0",
        "data": {"first_date": first, "last_date": last},
        "settings": {"top": top},
        "site": {"adjusted_change": adjusted, "lost_clicks": lost, "status_counts": {}},
        "refresh_priorities": pages,
    }


OLD = report(
    [
        page("https://ex.com/a", "decaying", 90.0),
        page("https://ex.com/b", "watch", 40.0),
        page("https://ex.com/c", "decaying", 70.0),
        page("https://ex.com/d", "watch", 20.0),
    ]
)
NEW = report(
    [
        page("https://ex.com/a", "decaying", 80.0, 120.0),
        page("https://ex.com/b", "decaying", 60.0),
        page("https://ex.com/c", "watch", 30.0),
        page("https://ex.com/e", "decaying", 95.0, 300.0),
    ],
    first="2026-02-02",
    last="2026-07-26",
    adjusted=-0.2,
    lost=800.0,
)


def kinds(cmp):
    return {c.page.rsplit("/", 1)[1]: c.kind for c in cmp.changes}


def test_classifies_every_page():
    cmp = compare_reports(OLD, NEW)
    assert kinds(cmp) == {"a": "unchanged", "b": "worse", "c": "better", "d": "resolved", "e": "new"}
    assert [c.page[-1] for c in cmp.regressions] == ["e", "b"]
    a = next(c for c in cmp.changes if c.page.endswith("/a"))
    assert a.priority_change == -10.0
    # Ordered by priority, highest first.
    assert [c.page[-1] for c in cmp.changes] == ["e", "a", "b", "c", "d"]


def test_to_dict_counts_and_site():
    data = compare_reports(OLD, NEW).to_dict()
    assert data["counts"] == {"new": 1, "worse": 1, "better": 1, "resolved": 1, "unchanged": 1}
    assert data["comparison"] == {"old": "2026-01-05 to 2026-06-28", "new": "2026-02-02 to 2026-07-26"}
    assert data["site"]["new_lost_clicks"] == 800.0
    assert data["pages"]["resolved"][0]["new_status"] is None


def test_text_and_markdown():
    cmp = compare_reports(OLD, NEW)
    text = render_text(cmp)
    assert "pages: 1 new, 1 worse, 1 better, 1 resolved, 1 unchanged" in text
    assert "Newly flagged:\n  https://ex.com/e  (decaying, priority 95.0, lost 300 clicks)" in text
    assert "https://ex.com/d  (was watch, priority 20.0)" in text
    assert "note:" not in text
    md = render_markdown(cmp)
    assert "## Worse (watch -> decaying) (1)" in md
    assert "| https://ex.com/b | watch -> decaying | 60.0 | 100 |" in md
    assert "| Site clicks after seasonality | -10% | -20% |" in md


def test_identical_reports():
    cmp = compare_reports(OLD, OLD)
    assert {c.kind for c in cmp.changes} == {"unchanged"}
    assert "No pages changed status." in render_markdown(cmp)


def test_full_list_note():
    new = report([page("https://ex.com/x", "decaying", 50.0)], top=1)
    text = render_text(compare_reports(OLD, new))
    assert "may only rank lower" in text


def test_load_report_errors(tmp_path: Path):
    with pytest.raises(CompareError, match="no such file"):
        load_report(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CompareError, match="not a JSON file"):
        load_report(bad)
    other = tmp_path / "other.json"
    other.write_text('{"tool": "something-else"}', encoding="utf-8")
    with pytest.raises(CompareError, match="not a content-decay-finder JSON report"):
        load_report(other)


def write(tmp_path: Path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def run(args):
    out = io.StringIO()
    return main(args, out=out), out.getvalue()


def test_cli_compare_and_fail_on_new(tmp_path: Path):
    old, new = write(tmp_path, "old.json", OLD), write(tmp_path, "new.json", NEW)
    code, out = run(["compare", old, new])
    assert code == 0 and "Newly flagged:" in out
    assert run(["compare", old, new, "--fail-on-new", "2"])[0] == 1
    assert run(["compare", old, new, "--fail-on-new", "3"])[0] == 0
    code, out = run(["compare", old, new, "-f", "json"])
    assert json.loads(out)["counts"]["new"] == 1
    target = tmp_path / "out" / "changes.md"
    code, out = run(["compare", old, new, "-f", "markdown", "-o", str(target)])
    assert code == 0 and target.read_text(encoding="utf-8").startswith("# Content decay")


def test_cli_compare_bad_input(tmp_path: Path, capsys):
    old = write(tmp_path, "old.json", OLD)
    assert run(["compare", old, str(tmp_path / "nope.json")])[0] == 2
    assert "no such file" in capsys.readouterr().err


def test_compare_real_reports(tmp_path: Path):
    from content_decay_finder.analyze import analyze
    from synth import standard_dataset

    result = analyze(standard_dataset())
    data = result.to_dict()
    assert data["settings"]["top"] == 50
    cmp = compare_reports(data, data)
    assert cmp.changes and all(c.kind == "unchanged" for c in cmp.changes)
