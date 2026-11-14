import gzip
from datetime import date
from pathlib import Path

import pytest

from content_decay_finder.loader import (
    Dataset,
    LoadError,
    iter_rows,
    load_csv,
    load_paths,
    map_columns,
    parse_date,
    parse_number,
    write_csv,
)
from content_decay_finder.model import Row


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,234", 1234),
        ("12", 12),
        ("4.5%", 0.045),
        ("1.234,5", 1234.5),
        ("1,234.5", 1234.5),
        ("0,5", 0.5),
        ("", 0),
        ("-", 0),
        ("11.75%", 0.1175),
        ("1 234", 1234),
    ],
)
def test_parse_number(text, value):
    assert parse_number(text) == pytest.approx(value)


@pytest.mark.parametrize(
    "text", ["2026-01-05", "2026/01/05", "20260105", "Jan 5, 2026", "5 Jan 2026", "January 5, 2026", "01/05/2026"]
)
def test_parse_date(text):
    assert parse_date(text) == date(2026, 1, 5)


def test_parse_date_rejects_garbage():
    with pytest.raises(LoadError):
        parse_date("yesterday")


def test_map_columns_aliases():
    cols = map_columns(["﻿Date", "Landing Page", "Url Clicks", "Impressions", "Average Position", "Query"])
    assert cols == {"date": 0, "page": 1, "clicks": 2, "impressions": 3, "position": 4, "query": 5}


def test_native_format_query_column_routes_rows(fixtures: Path):
    ds = load_csv(fixtures / "native.csv")
    # the file has a query column, so even an empty query makes it query-level data
    assert len(ds.query_rows) == 1 and not ds.page_rows


def test_looker_export_normalizes_urls(fixtures: Path):
    ds = load_csv(fixtures / "looker.csv")
    assert [r.page for r in ds.page_rows] == ["https://www.example.com/blog/post/"] * 2
    first = ds.page_rows[0]
    assert (first.clicks, first.impressions, first.position) == (1234, 10500, 4.5)
    kept = load_csv(fixtures / "looker.csv", strip_query=False)
    assert kept.page_rows[0].page == "https://www.example.com/blog/post/?utm_source=x"


def test_bigquery_export_position_from_sum(fixtures: Path):
    ds = load_paths([fixtures / "bigquery-semicolon.csv"])
    widget = next(r for r in ds.query_rows if r.query == "widget")
    assert widget.position == pytest.approx(3.0)  # 20 / 10 + 1
    gadget = next(r for r in ds.query_rows if r.query == "gadget")
    assert gadget.position == pytest.approx(1.0)
    # page rows were derived from the query rows
    assert ds.page_level_derived
    assert ds.page_rows[0].clicks == 4 and ds.page_rows[0].impressions == 15
    assert ds.page_rows[0].position == pytest.approx((3 * 10 + 1 * 5) / 15)


def test_ui_export_without_dates_explains(fixtures: Path):
    with pytest.raises(LoadError, match="no per-page dates"):
        load_csv(fixtures / "ui-pages-export.csv")


def test_bad_rows_report_line_numbers():
    with pytest.raises(LoadError, match=":3:"):
        list(iter_rows(["date,page,clicks,impressions\n", "2026-01-05,/a,1,2\n", "2026-01-06,/a,x,2\n"]))
    with pytest.raises(LoadError, match="negative"):
        list(iter_rows(["date,page,clicks,impressions\n", "2026-01-05,/a,-1,2\n"]))
    with pytest.raises(LoadError, match="empty"):
        list(iter_rows([]))


def test_blank_lines_and_pages_are_skipped():
    rows = list(iter_rows(["date,page,clicks,impressions\n", "\n", "2026-01-05,,1,2\n", "2026-01-05,/a,1,2\n"]))
    assert len(rows) == 1


def test_directories_gzip_and_roundtrip(tmp_path: Path):
    rows = [
        Row(date(2026, 1, 5), "https://e.example/a", 3, 30, 4.25, "q"),
        Row(date(2026, 1, 6), "https://e.example/a", 1, 10, None, "q"),
    ]
    write_csv(rows, tmp_path / "data" / "queries.csv", with_query=True)
    page_rows = [Row(date(2026, 1, 5), "https://e.example/a", 5, 50, 3.0)]
    write_csv(page_rows, tmp_path / "data" / "pages.csv", with_query=False)
    raw = (tmp_path / "data" / "pages.csv").read_bytes()
    (tmp_path / "data" / "pages.csv").unlink()
    (tmp_path / "data" / "pages.csv.gz").write_bytes(gzip.compress(raw))
    ds = load_paths([tmp_path / "data"])
    assert len(ds.query_rows) == 2 and len(ds.page_rows) == 1
    assert not ds.page_level_derived
    assert ds.query_rows[1].position is None
    assert ds.date_range == (date(2026, 1, 5), date(2026, 1, 5))


def test_load_paths_errors(tmp_path: Path):
    with pytest.raises(LoadError):
        load_paths([])
    with pytest.raises(LoadError, match="not found"):
        load_paths([tmp_path / "missing.csv"])
    assert Dataset().date_range is None
