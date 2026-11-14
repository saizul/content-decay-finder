from datetime import date

import pytest

from content_decay_finder.model import Row, Totals
from content_decay_finder.stats import clamp, linear_trend, mean, pct_change, theil_sen_slope
from content_decay_finder.weekly import build_series, full_weeks, make_windows, week_start


def test_linear_trend_exact_line():
    t = linear_trend([10, 8, 6, 4, 2])
    assert t.slope == pytest.approx(-2)
    assert t.intercept == pytest.approx(10)
    assert t.r2 == pytest.approx(1)
    assert t.relative_slope == pytest.approx(-2 / 6)


def test_linear_trend_edge_cases():
    assert linear_trend([]).slope == 0
    assert linear_trend([5]).mean == 5
    flat = linear_trend([3, 3, 3])
    assert flat.slope == 0 and flat.r2 == 0
    noisy = linear_trend([1, 5, 1, 5, 1, 5])
    assert 0 <= noisy.r2 < 0.2


def test_theil_sen_ignores_outlier():
    values = [10, 11, 12, 100, 14, 15]
    assert theil_sen_slope(values) == pytest.approx(1.0)
    assert theil_sen_slope([1]) == 0


def test_pct_change_and_helpers():
    assert pct_change(100, 80) == pytest.approx(-0.2)
    assert pct_change(0, 0) is None
    assert pct_change(0, 5) == float("inf")
    assert mean([]) == 0
    assert clamp(5, 0, 1) == 1


def test_week_start_and_full_weeks():
    assert week_start(date(2026, 1, 8)) == date(2026, 1, 5)
    # Wed 2026-01-07 .. Tue 2026-02-03: the partial first and last weeks are dropped
    weeks = full_weeks(date(2026, 1, 7), date(2026, 2, 3))
    assert weeks == [date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 26)]
    assert full_weeks(date(2026, 1, 5), date(2026, 1, 11)) == [date(2026, 1, 5)]
    assert full_weeks(date(2026, 1, 6), date(2026, 1, 10)) == []


def test_build_series_weights_position_by_impressions():
    weeks = [date(2026, 1, 5)]
    rows = [
        Row(date(2026, 1, 5), "/a", 1, 100, 2.0),
        Row(date(2026, 1, 6), "/a", 1, 300, 6.0),
        Row(date(2026, 3, 1), "/a", 9, 9, 1.0),
    ]
    s = build_series(rows, weeks)["/a"]
    assert s.clicks() == [2]
    assert s.positions()[0] == pytest.approx(5.0)
    assert s.window(0, 1).impressions == 400


def test_totals():
    t = Totals()
    t.add(1, 0, 5.0)
    assert t.position is None and t.ctr == 0


def test_windows():
    w = make_windows(70, 4, 8, 16)
    assert w.recent == (66, 70) and w.baseline == (58, 66) and w.trend == (54, 70)
    assert w.yoy_recent == (14, 18) and w.yoy_baseline == (6, 14)
    assert make_windows(63, 4, 8, 16).yoy_recent is None
    assert make_windows(11, 4, 8, 16) is None
    assert make_windows(12, 4, 8, 40).trend == (0, 12)
