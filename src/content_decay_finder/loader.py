"""Loading Search Console data from CSV files.

Accepted inputs (the columns are recognised by name, case-insensitively, in any order):

- this tool's own format, written by ``content-decay-finder fetch``: ``date,page,query,clicks,impressions,ctr,position``
- exports from Looker Studio, Sheets add-ons or the API with columns such as ``Date``, ``Landing Page``/``URL``/
  ``Page``, ``Query``, ``Url Clicks``/``Clicks``, ``Impressions``, ``Average Position``/``Position``
- the BigQuery bulk export tables (``data_date``, ``url``, ``query``, ``clicks``, ``impressions``, ``sum_position``),
  where the average position is ``sum_position / impressions + 1``

The performance report export of the Search Console web interface has no date column per page, so it cannot be
used for trends on its own.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from content_decay_finder.model import Row
from content_decay_finder.urls import normalize_url

ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "data_date", "day", "datum", "fecha"),
    "page": ("page", "url", "landing page", "landing_page", "top pages", "pages", "address", "page url", "landingpage"),
    "query": ("query", "queries", "top queries", "search query", "keyword", "keywords"),
    "clicks": ("clicks", "url clicks", "url_clicks", "total clicks"),
    "impressions": ("impressions", "impr", "total impressions"),
    "ctr": ("ctr", "url ctr", "site ctr", "average ctr"),
    "position": ("position", "average position", "avg position", "avg. position", "avg_position"),
    "sum_position": ("sum_position", "sum_top_position"),
}
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%m/%d/%Y")


class LoadError(ValueError):
    pass


@dataclass
class Dataset:
    """Page-level rows (date + page) and query-level rows (date + page + query)."""

    page_rows: list[Row] = field(default_factory=list)
    query_rows: list[Row] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    page_level_derived: bool = False

    def extend(self, other: Dataset) -> None:
        self.page_rows += other.page_rows
        self.query_rows += other.query_rows
        self.sources += other.sources

    def finalize(self) -> Dataset:
        """Without page-level rows, sum the query rows per day and page (an underestimate: Search Console leaves
        out anonymised queries)."""
        if not self.page_rows and self.query_rows:
            sums: dict[tuple[date, str], list[float]] = {}
            for r in self.query_rows:
                acc = sums.setdefault((r.date, r.page), [0.0, 0.0, 0.0])
                acc[0] += r.clicks
                acc[1] += r.impressions
                if r.position is not None:
                    acc[2] += r.position * r.impressions
            self.page_rows = [Row(d, p, c, i, (w / i) if i else None) for (d, p), (c, i, w) in sorted(sums.items())]
            self.page_level_derived = True
        return self

    @property
    def has_queries(self) -> bool:
        return bool(self.query_rows)

    @property
    def date_range(self) -> tuple[date, date] | None:
        rows = self.page_rows or self.query_rows
        if not rows:
            return None
        days = [r.date for r in rows]
        return min(days), max(days)


def _norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("﻿", "").strip().strip('"').lower())


def map_columns(header: list[str]) -> dict[str, int]:
    normalized = [_norm_header(h) for h in header]
    mapping: dict[str, int] = {}
    for field_name, aliases in ALIASES.items():
        for idx, name in enumerate(normalized):
            if name in aliases:
                mapping.setdefault(field_name, idx)
                break
    return mapping


def parse_number(text: str) -> float:
    """``1,234`` -> 1234, ``4.5%`` -> 0.045, ``"12"`` -> 12. Empty means 0."""
    value = text.strip().replace(" ", "").replace(" ", "")
    if not value or value in ("-", "--"):
        return 0.0
    percent = value.endswith("%")
    value = value.rstrip("%")
    if "," in value and "." in value:
        # 1,234.5 (English) or 1.234,5 (German)
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        head, _, tail = value.rpartition(",")
        value = value.replace(",", "") if len(tail) == 3 and head else value.replace(",", ".")
    number = float(value)
    return number / 100 if percent else number


def parse_date(text: str) -> date:
    value = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise LoadError(f"unrecognised date {text!r} (use YYYY-MM-DD)")


def _open_text(path: Path) -> io.TextIOBase:
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8-sig", newline="")
    return path.open(encoding="utf-8-sig", newline="")


def _sniff(sample: str) -> type[csv.Dialect] | csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def iter_rows(lines: Iterable[str], source: str = "<input>", strip_query: bool = True) -> Iterator[Row]:
    lines = iter(lines)
    buffered = []
    for line in lines:
        buffered.append(line)
        if len(buffered) >= 5:
            break
    dialect = _sniff("".join(buffered))
    reader = csv.reader(_chain(buffered, lines), dialect)
    header = next(reader, None)
    if header is None:
        raise LoadError(f"{source}: empty file")
    cols = map_columns(header)
    missing = [name for name in ("date", "page", "clicks", "impressions") if name not in cols]
    if missing:
        hint = " (the Search Console web export has no per-page dates; use 'fetch' or a date+page export)"
        raise LoadError(f"{source}: missing column(s) {', '.join(missing)}{hint if 'date' in missing else ''}")
    for line_no, record in enumerate(reader, start=2):
        if not record or all(not cell.strip() for cell in record):
            continue
        try:
            day = parse_date(record[cols["date"]])
            page = normalize_url(record[cols["page"]], strip_query)
            clicks = parse_number(record[cols["clicks"]])
            impressions = parse_number(record[cols["impressions"]])
            position: float | None = None
            if "position" in cols and record[cols["position"]].strip():
                position = parse_number(record[cols["position"]])
            elif "sum_position" in cols and impressions:
                # BigQuery bulk export: zero-based sum of the topmost position
                position = parse_number(record[cols["sum_position"]]) / impressions + 1
            query = record[cols["query"]].strip() if "query" in cols else None
        except (IndexError, ValueError) as exc:
            raise LoadError(f"{source}:{line_no}: {exc}") from exc
        if not page:
            continue
        if clicks < 0 or impressions < 0 or (position is not None and position < 0):
            raise LoadError(f"{source}:{line_no}: negative values")
        yield Row(day, page, clicks, impressions, position, query)


def _chain(first: list[str], rest: Iterator[str]) -> Iterator[str]:
    yield from first
    yield from rest


def load_csv(path: Path, strip_query: bool = True) -> Dataset:
    dataset = Dataset(sources=[str(path)])
    with _open_text(path) as handle:
        for row in iter_rows(handle, str(path), strip_query):
            if row.query is not None:
                dataset.query_rows.append(row)
            else:
                dataset.page_rows.append(row)
    return dataset


def load_paths(paths: Iterable[Path], strip_query: bool = True) -> Dataset:
    """Load files and directories (every ``*.csv`` / ``*.csv.gz`` inside)."""
    dataset = Dataset()
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files += sorted([*path.glob("*.csv"), *path.glob("*.csv.gz")])
        else:
            files.append(path)
    if not files:
        raise LoadError("no CSV files given")
    for file in files:
        if not file.is_file():
            raise LoadError(f"{file}: not found")
        dataset.extend(load_csv(file, strip_query))
    return dataset.finalize()


def write_csv(rows: Iterable[Row], path: Path, with_query: bool) -> int:
    """Write rows in this tool's own format (the one ``fetch`` produces)."""
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        header = ["date", "page", *(["query"] if with_query else []), "clicks", "impressions", "ctr", "position"]
        writer.writerow(header)
        for r in rows:
            pos = "" if r.position is None else f"{r.position:.2f}"
            writer.writerow(
                [
                    r.date.isoformat(),
                    r.page,
                    *([r.query or ""] if with_query else []),
                    f"{r.clicks:g}",
                    f"{r.impressions:g}",
                    f"{r.ctr:.4f}",
                    pos,
                ]
            )
            count += 1
    return count
