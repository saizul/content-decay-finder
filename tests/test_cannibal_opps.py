import pytest

from content_decay_finder import AnalysisConfig, analyze
from content_decay_finder.cannibalization import find_cannibalization
from content_decay_finder.loader import Dataset
from content_decay_finder.model import Row
from content_decay_finder.opportunities import DEFAULT_CTR, ctr_curve
from synth import START, daily_rows, page, standard_dataset, steady


def test_alternating_leader_is_flagged(result):
    assert [c.query for c in result.cannibalization] == ["best widget"]
    case = result.cannibalization[0]
    assert case.switches == 11  # 12 weeks (baseline + recent), leader changes every week
    assert {p.page.rsplit("/", 2)[-2] if p.page.endswith("/") else p.page.rsplit("/", 1)[-1] for p in case.pages} == {
        "widget-review",
        "widget",
    }
    assert sum(p.weeks_leading for p in case.pages) == 12
    assert pytest.approx(sum(p.share for p in case.pages)) == 1.0
    assert case.score > 0


def test_single_page_query_is_not_flagged(result):
    assert "example brand" not in [c.query for c in result.cannibalization]


def test_leader_change_between_windows_is_flagged():
    weeks = 12
    rows = []
    rows += daily_rows(page("/old"), lambda w: (10, 100, 3.0) if w < 8 else (1, 30, 12.0), weeks, query="q")
    rows += daily_rows(page("/new"), lambda w: (1, 30, 12.0) if w < 8 else (10, 100, 3.0), weeks, query="q")
    weeks_list = sorted({START} | {r.date for r in rows if r.date.weekday() == 0})
    cases = find_cannibalization(rows, weeks_list, (0, 8), (8, 12), AnalysisConfig())
    assert len(cases) == 1
    assert cases[0].switches == 1
    assert cases[0].baseline_leader.endswith("/old") and cases[0].recent_leader.endswith("/new")


def test_small_share_and_low_impressions_are_ignored():
    rows = daily_rows(page("/a"), steady(5, 95, 3), 12, query="q") + daily_rows(
        page("/b"), steady(0, 2, 30), 12, query="q"
    )
    weeks_list = sorted({r.date for r in rows if r.date.weekday() == 0})
    assert find_cannibalization(rows, weeks_list, (0, 8), (8, 12), AnalysisConfig()) == []
    rows = daily_rows(page("/a"), steady(1, 1, 3), 12, query="q") + daily_rows(
        page("/b"), steady(1, 1, 3), 12, query="q"
    )
    assert find_cannibalization(rows, weeks_list, (0, 8), (8, 12), AnalysisConfig(cannibal_min_impressions=500)) == []
    assert find_cannibalization([], [], (0, 0), (0, 0), AnalysisConfig()) == []


def test_almost_page_one(result):
    pages = [(o.page, o.query) for o in result.opportunities]
    assert pages == [("https://www.example.com/guides/almost/", None)]
    opp = result.opportunities[0]
    assert opp.position == pytest.approx(12.5)
    assert opp.impressions == 300 * 28
    assert opp.extra_clicks == pytest.approx(opp.impressions * (opp.target_ctr - opp.ctr))
    assert [(o.query) for o in result.query_opportunities] == ["widget guide"]


def test_opportunity_range_is_configurable():
    cfg = AnalysisConfig(opportunity_min_position=13, opportunity_max_position=20)
    assert analyze(standard_dataset(), cfg).opportunities == []


def test_ctr_curve_uses_own_data_and_is_monotonic():
    rows = [Row(START, "/a", 400, 1000, 1.2), Row(START, "/b", 300, 1000, 2.0), Row(START, "/c", 5, 10, 3.0)]
    curve = ctr_curve(rows)
    assert curve[1] == pytest.approx(0.4)
    assert curve[2] == pytest.approx(0.3)
    assert curve[3] == DEFAULT_CTR[3]  # too few impressions at position 3
    assert all(curve[i] >= curve[i + 1] for i in range(1, 10))
    odd = ctr_curve([Row(START, "/a", 10, 1000, 1.0), Row(START, "/b", 500, 1000, 2.0)])
    assert odd[2] == pytest.approx(0.01)  # capped by position 1


def test_no_query_data_note():
    ds = Dataset(page_rows=daily_rows(page("/p"), steady(), 14)).finalize()
    result = analyze(ds)
    assert result.cannibalization == [] and not result.has_queries
    assert any("cannibalisation needs" in n for n in result.notes)
