import math

import pytest

from content_decay_finder import AnalysisConfig, analyze
from content_decay_finder.analyze import AnalysisError
from content_decay_finder.loader import Dataset
from synth import daily_rows, decaying, page, seasonal, standard_dataset, steady


def by_page(result):
    return {p.page.removeprefix("https://www.example.com"): p for p in result.pages}


def test_statuses(result):
    pages = by_page(result)
    assert pages["/blog/decaying-guide/"].status == "decaying"
    assert pages["/blog/ctr-drop/"].status == "decaying"
    assert pages["/blog/growing/"].status == "growing"
    assert pages["/products/widget"].status == "stable"
    assert pages["/products/tiny"].status == "low-data"
    assert pages["/new-page"].status == "new"
    assert pages["/"].status == "stable"


def test_causes(result):
    pages = by_page(result)
    assert "position" in pages["/blog/decaying-guide/"].causes
    ctr = pages["/blog/ctr-drop/"]
    assert ctr.causes == ["ctr"]
    assert ctr.position_change == pytest.approx(0)


def test_priority_formula_and_ranking(result):
    ranked = result.ranked()
    assert [p.status for p in ranked] == ["decaying", "decaying"]
    top = ranked[0]
    assert top.priority == pytest.approx(100)
    assert top.priority_raw == pytest.approx(top.lost_clicks * top.steepness * top.current_impressions)
    assert 0 < ranked[1].priority < 100
    for p in result.pages:
        if p.status not in ("decaying", "watch"):
            assert p.priority_raw == 0


def test_lost_clicks_and_steepness():
    weeks = 30
    ds = Dataset(page_rows=daily_rows(page("/p"), decaying(weeks, weeks - 10), weeks)).finalize()
    r = analyze(ds).pages[0]
    # baseline (weeks 18-25) mixes steady and declining weeks; recent is the bottom of the decline
    assert r.recent_clicks < r.baseline_clicks
    assert r.lost_clicks == pytest.approx((r.expected_clicks - r.recent_clicks) * 4)
    assert r.steepness > 0.02
    assert r.clicks_trend.r2 > 0.8
    assert len(r.weekly_clicks) == 16


def test_too_little_data():
    ds = Dataset(page_rows=daily_rows(page("/p"), steady(), 8)).finalize()
    with pytest.raises(AnalysisError, match="at least 12"):
        analyze(ds)
    with pytest.raises(AnalysisError):
        analyze(Dataset())


def seasonal_dataset(weeks: int = 70, other_pages: bool = True) -> Dataset:
    # cycle: low season in weeks 44-51 of each 52-week cycle; recent window = weeks 66-69 -> cycle weeks 14-17;
    # shift the low season so that it falls in the recent window both this year and last year
    rows = daily_rows(page("/blog/seasonal/"), seasonal(52, low_start=14, low_len=4), weeks)
    if other_pages:
        rows += daily_rows(page("/blog/steady/"), steady(), weeks)
    return Dataset(page_rows=rows).finalize()


def test_seasonality_cancels_a_yearly_dip():
    with_season = by_page(analyze(seasonal_dataset()))["/blog/seasonal/"]
    assert with_season.clicks_change == pytest.approx(-0.6)
    assert with_season.seasonal.source == "page"
    assert with_season.seasonal.factor == pytest.approx(0.4)
    assert with_season.adjusted_change == pytest.approx(0)
    assert with_season.status == "stable"
    assert with_season.lost_clicks == pytest.approx(0)
    off = by_page(analyze(seasonal_dataset(), AnalysisConfig(seasonality="off")))["/blog/seasonal/"]
    assert off.status == "decaying"
    assert off.seasonal.source == "none"


def test_site_level_seasonality_fallback():
    weeks = 70
    rows = daily_rows(page("/blog/seasonal/"), seasonal(52, low_start=14, low_len=4, clicks=500), weeks)
    # a page that only exists this year inherits the site's seasonal factor
    rows += daily_rows(page("/blog/young/"), seasonal(52, low_start=14, low_len=4), weeks, first_week=40)
    result = analyze(Dataset(page_rows=rows).finalize())
    young = by_page(result)["/blog/young/"]
    assert young.seasonal.source == "site"
    assert young.status == "stable"
    assert result.site.seasonal_source == "page"  # the site series is seasonal on its own
    assert result.site.adjusted_change == pytest.approx(0, abs=1e-9)


def test_no_yoy_note(result):
    assert any("year-over-year needs 64" in n for n in result.notes)


def test_to_dict_is_json_safe(result):
    import json

    data = result.to_dict()
    text = json.dumps(data)
    assert "Infinity" not in text and "NaN" not in text
    new = next(p for p in data["refresh_priorities"]) if data["refresh_priorities"] else None
    assert new is not None
    assert data["site"]["pages"] == 8
    assert math.isinf(by_page(result)["/new-page"].clicks_change)


def test_ignore_patterns():
    import re

    cfg = AnalysisConfig(ignore_patterns=[re.compile(r"/blog/")])
    pages = by_page(analyze(standard_dataset(), cfg))
    assert not any(p.startswith("/blog/") for p in pages)


def test_watch_status():
    weeks = 30

    def mild(w: int):
        return (50.0 if w < weeks - 4 else 43.0), 1000.0, 4.0

    r = analyze(Dataset(page_rows=daily_rows(page("/p"), mild, weeks)).finalize()).pages[0]
    assert r.status == "watch"
    assert r.adjusted_change == pytest.approx(-0.14)


def test_auto_seasonality_takes_the_lower_factor():
    weeks = 70
    rows = daily_rows(page("/blog/linear-growth/"), lambda w: (8 + w * 0.6, 300 + w * 14, 6.0), weeks)
    rows += daily_rows(page("/blog/steady/"), steady(200, 3000, 3.0), weeks)
    result = analyze(Dataset(page_rows=rows).finalize())
    grower = by_page(result)["/blog/linear-growth/"]
    # last year the page grew ~25% between the windows; that is its growth, not a season
    assert grower.seasonal.source == "site"
    assert grower.status != "watch" and grower.status != "decaying"
    page_only = by_page(analyze(Dataset(page_rows=rows).finalize(), AnalysisConfig(seasonality="page")))
    assert page_only["/blog/linear-growth/"].seasonal.factor > 1.15
    assert page_only["/blog/linear-growth/"].status == "watch"


def test_sample_data_end_to_end():
    from pathlib import Path

    from content_decay_finder import load_paths

    data = Path(__file__).parent.parent / "examples" / "sample-data"
    result = analyze(load_paths([data]))
    ranked = [p.page.removeprefix("https://www.example.com") for p in result.ranked()]
    assert ranked[:2] == ["/blog/wordpress-speed-guide/", "/blog/core-web-vitals-checklist/"]
    pages = by_page(result)
    summer = pages["/blog/summer-sale-hosting-deals/"]
    assert summer.clicks_change < -0.5 and summer.status == "stable"  # the yearly drop after the summer
    assert pages["/blog/new-hosting-benchmarks-2026/"].status == "new"
    assert [c.query for c in result.cannibalization] == ["wordpress speed"]
    opp_pages = {o.page.removeprefix("https://www.example.com") for o in result.opportunities}
    assert {"/tools/redirect-checker/", "/blog/cloudpanel-vs-cyberpanel/"} <= opp_pages
