"""Command-line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import TextIO

from content_decay_finder._version import __version__
from content_decay_finder.analyze import AnalysisError, AnalysisResult, analyze
from content_decay_finder.config import AnalysisConfig, ConfigError, load_config_file, parse_section_rule
from content_decay_finder.gsc_api import ApiError, Signer, default_dates, make_client, parse_filter
from content_decay_finder.http import Transport
from content_decay_finder.loader import Dataset, LoadError, load_paths, write_csv
from content_decay_finder.report import FORMATS, write_reports
from content_decay_finder.report.format import delta_pos, num, pct, pos

log = logging.getLogger("content_decay_finder")
EXIT_OK, EXIT_DECAY, EXIT_ERROR = 0, 1, 2


def _formats(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        for item in value.split(","):
            item = {"md": "markdown"}.get(item.strip().lower(), item.strip().lower())
            if item == "all":
                out += [f for f in FORMATS if f not in out]
            elif item in FORMATS:
                if item not in out:
                    out.append(item)
            elif item:
                raise ConfigError(f"unknown format {item!r} (choose from {', '.join(FORMATS)}, all)")
    return out


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}") from exc


def _add_api_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("Search Console API")
    g.add_argument("--site-url", help="property: https://www.example.com/ or sc-domain:example.com")
    g.add_argument("--credentials", type=Path, help="service account JSON key (or GOOGLE_APPLICATION_CREDENTIALS)")
    g.add_argument("--access-token-env", metavar="VAR", help="read an OAuth access token from this variable instead")
    g.add_argument("--start", type=_date, help="first day (default: 16 months before --end)")
    g.add_argument("--end", type=_date, help="last day (default: 3 days ago)")
    g.add_argument("--search-type", default="web", help="web, image, video, news, discover, googleNews")
    g.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="EXPR",
        help="dimension filter, e.g. page~/blog/ or query!~brand (repeatable, combined with AND)",
    )
    g.add_argument("--data-state", default="final", choices=["final", "all"])
    g.add_argument("--chunk-days", type=int, default=7, help="days per API request window (default 7)")
    g.add_argument("--no-queries", action="store_true", help="skip date+page+query rows (no cannibalisation)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="content-decay-finder",
        description="Find decaying pages in Google Search Console data and rank them for a refresh.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    a = sub.add_parser("analyze", help="analyse CSV exports or data from the API and write reports")
    a.add_argument("inputs", nargs="*", type=Path, help="CSV files or directories (omit with --site-url)")
    a.add_argument("--config", type=Path, help="TOML file with [analysis] settings")
    a.add_argument("-f", "--format", action="append", default=[], help="csv, json, markdown, html or all")
    a.add_argument("-o", "--output-dir", type=Path, default=Path("content-decay-report"))
    a.add_argument("--basename", default="content-decay")
    a.add_argument("--save-csv", type=Path, metavar="DIR", help="with --site-url: also save the fetched rows")
    a.add_argument("--fail-on-decay", type=int, metavar="N", help="exit with 1 when N or more pages are decaying")
    a.add_argument("--quiet", action="store_true", help="no summary on stdout")
    t = a.add_argument_group("analysis settings (override the config file)")
    t.add_argument("--recent-weeks", type=int)
    t.add_argument("--baseline-weeks", type=int)
    t.add_argument("--trend-weeks", type=int)
    t.add_argument("--decline-threshold", type=float, help="drop that counts as decay, e.g. 0.2 for 20%%")
    t.add_argument("--min-clicks", type=float, dest="min_baseline_clicks", help="baseline clicks needed")
    t.add_argument("--seasonality", choices=["auto", "page", "site", "off"])
    t.add_argument("--section-depth", type=int, help="path segments per section (default 1)")
    t.add_argument("--section", action="append", default=[], metavar="NAME=REGEX", help="named section rule")
    t.add_argument("--ignore", action="append", default=[], metavar="REGEX", help="skip matching URLs")
    t.add_argument("--keep-query-strings", action="store_true", help="treat ?a=b URLs as separate pages")
    t.add_argument("--opp-min-position", type=float, dest="opportunity_min_position")
    t.add_argument("--opp-max-position", type=float, dest="opportunity_max_position")
    t.add_argument("--opp-min-impressions", type=float, dest="opportunity_min_impressions")
    t.add_argument("--top", type=int, help="rows per table in the reports (default 50)")
    _add_api_args(a)

    f = sub.add_parser("fetch", help="download Search Analytics data to CSV (pages.csv and queries.csv)")
    f.add_argument("-o", "--output-dir", type=Path, default=Path("gsc-data"))
    _add_api_args(f)
    return parser


def build_config(args: argparse.Namespace) -> AnalysisConfig:
    cfg = load_config_file(args.config) if args.config else AnalysisConfig()
    for name in (
        "recent_weeks",
        "baseline_weeks",
        "trend_weeks",
        "decline_threshold",
        "min_baseline_clicks",
        "seasonality",
        "section_depth",
        "opportunity_min_position",
        "opportunity_max_position",
        "opportunity_min_impressions",
        "top",
    ):
        value = getattr(args, name, None)
        if value is not None:
            setattr(cfg, name, value)
    if cfg.watch_threshold > cfg.decline_threshold:
        cfg.watch_threshold = cfg.decline_threshold / 2
    cfg.section_rules += [parse_section_rule(rule) for rule in args.section]
    import re

    try:
        cfg.ignore_patterns += [re.compile(p) for p in args.ignore]
    except re.error as exc:
        raise ConfigError(f"bad --ignore pattern: {exc}") from exc
    if args.keep_query_strings:
        cfg.strip_query_strings = False
    cfg.validate()
    return cfg


def fetch_dataset(
    args: argparse.Namespace, transport: Transport | None, signer: Signer | None, today: date | None = None
) -> Dataset:
    if not args.site_url:
        raise ConfigError("--site-url is required to use the API")
    client = make_client(args.credentials, args.access_token_env, transport, signer)
    start, end = default_dates(today or date.today())
    start = args.start or start
    end = args.end or end
    filters = [parse_filter(f) for f in args.filter]
    kwargs = {"search_type": args.search_type, "filters": filters, "data_state": args.data_state}
    if args.chunk_days < 1:
        raise ConfigError("--chunk-days must be at least 1")
    dataset = Dataset(sources=[f"api:{args.site_url}"])
    dataset.page_rows = list(client.fetch_rows(args.site_url, start, end, False, args.chunk_days, **kwargs))
    if not args.no_queries:
        dataset.query_rows = list(client.fetch_rows(args.site_url, start, end, True, args.chunk_days, **kwargs))
    return dataset.finalize()


def print_summary(result: AnalysisResult, out: TextIO, limit: int = 15) -> None:
    site = result.site
    out.write(
        f"{result.first_date} to {result.last_date}: {len(result.weeks)} full weeks, {site.pages} pages\n"
        f"site clicks/week {num(site.baseline_clicks)} -> {num(site.recent_clicks)} ({pct(site.clicks_change)}, "
        f"{pct(site.adjusted_change)} after seasonality)\n"
    )
    counts = ", ".join(f"{v} {k}" for k, v in site.status_counts.items())
    out.write(f"pages: {counts}\n")
    for note in result.notes:
        out.write(f"note: {note}\n")
    ranked = result.ranked()[:limit]
    if ranked:
        out.write("\nrefresh first:\n")
        for i, p in enumerate(ranked, 1):
            out.write(
                f"{i:>3}. [{p.priority:5.1f}] {p.page}\n"
                f"       {p.status}, lost {num(p.lost_clicks)} clicks, {pct(p.adjusted_change)} adj., "
                f"position {pos(p.recent_position)} ({delta_pos(p.position_change)}), "
                f"causes: {', '.join(p.causes) or '-'}\n"
            )
    if result.cannibalization:
        out.write(f"\ncannibalised queries: {len(result.cannibalization)} (top: {result.cannibalization[0].query!r})\n")
    if result.opportunities:
        out.write(f"almost page 1: {len(result.opportunities)} page(s)\n")


def main(
    argv: list[str] | None = None,
    *,
    out: TextIO | None = None,
    transport: Transport | None = None,
    signer: Signer | None = None,
    today: date | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=(logging.WARNING, logging.INFO, logging.DEBUG)[min(args.verbose, 2)], format="%(levelname)s %(message)s"
    )
    stdout = out or sys.stdout
    try:
        if args.command == "fetch":
            dataset = fetch_dataset(args, transport, signer, today)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            n = write_csv(dataset.page_rows, args.output_dir / "pages.csv", with_query=False)
            stdout.write(f"wrote {n} rows to {args.output_dir / 'pages.csv'}\n")
            if dataset.query_rows:
                n = write_csv(dataset.query_rows, args.output_dir / "queries.csv", with_query=True)
                stdout.write(f"wrote {n} rows to {args.output_dir / 'queries.csv'}\n")
            return EXIT_OK

        cfg = build_config(args)
        if args.site_url:
            if args.inputs:
                raise ConfigError("give either CSV inputs or --site-url, not both")
            dataset = fetch_dataset(args, transport, signer, today)
            if args.save_csv:
                write_csv(dataset.page_rows, args.save_csv / "pages.csv", with_query=False)
                if dataset.query_rows:
                    write_csv(dataset.query_rows, args.save_csv / "queries.csv", with_query=True)
        else:
            if not args.inputs:
                raise ConfigError("give CSV files or directories, or --site-url for the API")
            dataset = load_paths(args.inputs, strip_query=cfg.strip_query_strings)
        result = analyze(dataset, cfg)
        formats = _formats(args.format) if args.format else []
        if formats:
            for path in write_reports(result, formats, args.output_dir, args.basename):
                stdout.write(f"wrote {path}\n")
        if not args.quiet:
            print_summary(result, stdout)
        if args.fail_on_decay is not None and len(result.decaying) >= args.fail_on_decay:
            return EXIT_DECAY
        return EXIT_OK
    except (ConfigError, LoadError, AnalysisError, ApiError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
