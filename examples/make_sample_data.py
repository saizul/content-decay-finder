"""Create the sample dataset in examples/sample-data/ (synthetic, deterministic).

    python examples/make_sample_data.py

It covers 70 weeks for a made-up site, www.example.com, so year-over-year seasonality can be applied, and it
contains the patterns the tool looks for: a decaying guide, a CTR drop, a seasonal page (busy every summer), a
growing page, a page losing impressions, a query that moves between two pages and pages ranking on page 2.
"""

from __future__ import annotations

import csv
import gzip
import io
import random
from datetime import date, timedelta
from pathlib import Path

START = date(2025, 6, 2)  # Monday
WEEKS = 70
SITE = "https://www.example.com"
OUT = Path(__file__).parent / "sample-data"
rng = random.Random(20261114)


def noisy(value: float, spread: float = 0.12) -> float:
    return max(0.0, value * (1 + rng.uniform(-spread, spread)))


def weekday_factor(day: date) -> float:
    return 0.75 if day.weekday() >= 5 else 1.07


def pattern(path: str, w: int) -> tuple[float, float, float] | None:
    """(clicks/day, impressions/day, position) for week w, or None if the page does not exist yet."""
    late = max(0, w - (WEEKS - 12)) / 12  # 0 -> 1 over the last 12 weeks
    if path == "/blog/wordpress-speed-guide/":
        return 85 * (1 - 0.55 * late), 2400 * (1 - 0.25 * late), 2.4 + 4.5 * late
    if path == "/blog/core-web-vitals-checklist/":
        drop = 0.5 if w >= WEEKS - 5 else 1.0  # a new SERP feature took the clicks
        return 40 * drop, 1300, 3.1
    if path == "/blog/summer-sale-hosting-deals/":
        cycle = w % 52
        boost = 3.5 if 6 <= cycle < 14 else 1.0  # mid-July to the end of August, every year
        return 12 * boost, 600 * boost, 5.5
    if path == "/blog/vps-migration-checklist/":
        return 8 + w * 0.6, 300 + w * 14, 7.5 - w * 0.04
    if path == "/services/technical-seo-audit/":
        return 18, 700 * (1 - 0.45 * late), 4.0 + 1.5 * late
    if path == "/services/wordpress-maintenance/":
        return 25, 900, 3.5
    if path == "/tools/redirect-checker/":
        return 6, 650, 11.5
    if path == "/blog/cloudpanel-vs-cyberpanel/":
        return 4, 520, 14.0
    if path == "/blog/new-hosting-benchmarks-2026/":
        return (30, 900, 4.2) if w >= WEEKS - 5 else None
    if path == "/":
        return 60, 1500, 1.4
    if path == "/about/":
        return 0.4, 15, 9.0
    return None


PAGES = [
    "/",
    "/about/",
    "/blog/wordpress-speed-guide/",
    "/blog/core-web-vitals-checklist/",
    "/blog/summer-sale-hosting-deals/",
    "/blog/vps-migration-checklist/",
    "/blog/new-hosting-benchmarks-2026/",
    "/blog/cloudpanel-vs-cyberpanel/",
    "/services/technical-seo-audit/",
    "/services/wordpress-maintenance/",
    "/tools/redirect-checker/",
]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    page_rows = []
    query_rows = []
    for w in range(WEEKS):
        for d in range(7):
            day = START + timedelta(days=7 * w + d)
            f = weekday_factor(day)
            for path in PAGES:
                p = pattern(path, w)
                if p is None:
                    continue
                clicks, impressions, position = p
                c = round(noisy(clicks * f))
                i = max(c, round(noisy(impressions * f)))
                page_rows.append([day.isoformat(), SITE + path, c, i, round(noisy(position, 0.05), 2)])
            # "wordpress speed": the guide and the maintenance service page trade places every few weeks
            guide_leads = (w // 3) % 2 == 0
            for path, leads in (
                ("/blog/wordpress-speed-guide/", guide_leads),
                ("/services/wordpress-maintenance/", not guide_leads),
            ):
                c = round(noisy((9 if leads else 3) * f))
                i = round(noisy((140 if leads else 90) * f))
                query_rows.append(
                    [
                        day.isoformat(),
                        SITE + path,
                        "wordpress speed",
                        c,
                        max(c, i),
                        round(noisy(4.0 if leads else 8.5, 0.05), 2),
                    ]
                )
            for query, path, clicks, impressions, position in (
                ("example seo", "/", 25, 300, 1.2),
                ("redirect checker", "/tools/redirect-checker/", 3, 400, 11.8),
                ("cloudpanel vs cyberpanel", "/blog/cloudpanel-vs-cyberpanel/", 2, 300, 13.5),
            ):
                c = round(noisy(clicks * f))
                query_rows.append(
                    [
                        day.isoformat(),
                        SITE + path,
                        query,
                        c,
                        max(c, round(noisy(impressions * f))),
                        round(noisy(position, 0.05), 2),
                    ]
                )
    for name, header, rows in (
        ("pages.csv.gz", ["date", "page", "clicks", "impressions", "position"], page_rows),
        ("queries.csv.gz", ["date", "page", "query", "clicks", "impressions", "position"], query_rows),
    ):
        # mtime=0 and no file name in the gzip header keep the files byte-for-byte reproducible
        with (
            (OUT / name).open("wb") as raw,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz,
            io.TextIOWrapper(gz, encoding="utf-8", newline="") as handle,
        ):
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        print(f"wrote {OUT / name} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
