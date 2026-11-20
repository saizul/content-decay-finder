# content-decay-finder

[![CI](https://github.com/saizul/content-decay-finder/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/content-decay-finder/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Find the pages that are slowly losing Google traffic, and decide which ones to refresh first. It reads Google
Search Console performance data (CSV exports by date and page, or the Search Analytics API with a service
account), compares each page's recent weeks with its baseline, fits a weekly trend, corrects for seasonality with
last year's data, explains the likely cause (rankings, impressions or CTR), and ranks the pages by
**lost clicks × trend steepness × current impressions**. It also groups pages by URL section, flags queries that
move between pages (cannibalisation) and lists "almost page 1" pages ranking 8 to 20.

A page rarely dies overnight. It slips from position 3 to 6 over four months, a competitor's fresher article
takes the featured snippet, a new SERP feature eats the clicks while impressions stay flat. By the time a
dashboard shows it, the traffic has been gone for a quarter. A month-over-month comparison in the Search Console
interface also cannot tell a decaying page from a seasonal one. This tool can.

```console
$ content-decay-finder analyze examples/sample-data
2025-06-02 to 2026-10-04: 70 full weeks, 11 pages
site clicks/week 2,144 -> 1,856 (-13%, -5% after seasonality)
pages: 2 decaying, 1 low-data, 1 new, 7 stable

refresh first:
  1. [100.0] https://www.example.com/blog/wordpress-speed-guide/
       decaying, lost 474 clicks, -26% adj., position 6.0 (+2.3), causes: position
  2. [ 94.3] https://www.example.com/blog/core-web-vitals-checklist/
       decaying, lost 393 clicks, -42% adj., position 3.1 (+0.0), causes: ctr

cannibalised queries: 1 (top: 'wordpress speed')
almost page 1: 3 page(s)
```

The summer sale page in the same sample lost about 70% of its clicks, but it does that every September; after the
year-over-year adjustment it is `stable`.

## Contents

- [Features](#features)
- [Installation](#installation)
- [Docker image](#docker-image)
- [Getting the data](#getting-the-data)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Configuration](#configuration)
  - [Redirect maps](#redirect-maps)
- [Reports](#reports)
  - [Comparing two runs](#comparing-two-runs)
- [Library use](#library-use)
- [Examples](#examples)
- [Testing](#testing)
- [Security notes](#security-notes)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Inputs**: CSV files or directories (also `.csv.gz`) with a date and a page column: this tool's own format, Looker
  Studio and spreadsheet exports (`Landing Page`, `Url Clicks`, `Average Position`, `4.5%`, `1,234`, ...), and the
  Search Console BigQuery bulk export (`data_date`, `url`, `sum_position`). Comma, semicolon and tab separated.
- **Search Analytics API**: service-account authentication (JWT bearer flow, read-only scope), date chunking and
  `startRow` pagination at 25,000 rows per request, retries with backoff on 429/5xx, dimension filters, search
  type and `dataState`. `fetch` saves the data to CSV so you can analyse it again without calling the API.
- **Decay detection**: weekly buckets (Monday to Sunday, partial weeks dropped), recent vs baseline comparison,
  a least-squares trend with R² over the last 16 weeks for clicks, impressions and position.
- **Seasonality**: year-over-year expected change from the same weeks last year, per page or for the whole site.
- **Causes**: `position` (lost rankings), `impressions` (lost visibility), `ctr` (fewer clicks at the same
  position: snippets, SERP features, titles) and `seasonal`.
- **Refresh priority**: lost clicks × trend steepness × current impressions, on a 0-100 scale.
- **Sections**: pages grouped by the first path segment(s) or by your own named regular expressions, with totals,
  decay counts and section trends.
- **Cannibalisation**: queries where two or more pages share the impressions and the leading page keeps changing.
- **Almost page 1**: pages (and page + query pairs) at positions 8 to 20 with enough impressions, with an estimate
  of the extra clicks at position 3 from the site's own CTR curve.
- **Redirect maps**: merge the history of moved URLs into the page they redirect to (`--redirects`), so a
  migrated page is judged on its whole history instead of showing up as a decaying old URL and a new one. Reads
  `from,to` CSV files and crawler or redirect-plugin exports; chains are followed and loops rejected.
- **Reports**: CSV (one file per table), JSON, Markdown and a self-contained HTML page with inline SVG sparklines
  (no scripts, no external resources). `--fail-on-decay N` for scheduled CI jobs.
- **Compare runs**: `compare OLD.json NEW.json` lists pages that are newly flagged, went from watch to decaying,
  improved or recovered since the last report; `--fail-on-new N` fails a scheduled job only on new problems.

## Installation

Python 3.10 or newer. Analysing CSV files needs nothing else; the API needs `cryptography` to sign the service
account token.

```bash
pip install "content-decay-finder @ git+https://github.com/saizul/content-decay-finder"
# with the Search Console API
pip install "content-decay-finder[api] @ git+https://github.com/saizul/content-decay-finder"
```

This installs the `content-decay-finder` command (also available as `python -m content_decay_finder`).

## Docker image

A multi-arch image (linux/amd64, linux/arm64) is published to GitHub Packages, with the API extra installed:

```bash
docker pull ghcr.io/saizul/content-decay-finder:latest

# CSV files are read from /work, the working directory of the image
docker run --rm -v "$PWD:/work" ghcr.io/saizul/content-decay-finder:latest analyze gsc-data -f html -o report

# The API with a service account key mounted read-only
docker run --rm -v "$PWD:/work" -v "$HOME/keys/gsc.json:/keys/gsc.json:ro" \
  ghcr.io/saizul/content-decay-finder:latest analyze --site-url sc-domain:example.com \
  --credentials /keys/gsc.json -f all -o report
```

Release images are also tagged with the version (`ghcr.io/saizul/content-decay-finder:0.1.0`) and every build
with its commit SHA. The container runs as an unprivileged user (uid 10001); pass `--user "$(id -u)"` if it has
to write into a mounted directory you own.

## Getting the data

Trends need clicks and impressions **per page per day**. The performance report export of the Search Console web
interface has a "Pages" table without dates and a "Dates" table without pages, so it cannot be used on its own
(the tool says so if you try). Use one of these:

1. **The API (recommended)**. In Google Cloud, create a service account and a JSON key, enable the "Google Search
   Console API", then add the service account's email address as a user of the property in Search Console
   (Settings, Users and permissions; "Restricted" is enough). Then:

   ```bash
   content-decay-finder fetch --site-url sc-domain:example.com --credentials gsc.json -o gsc-data
   content-decay-finder analyze gsc-data -f all
   ```

   `--site-url` is the property exactly as Search Console names it: `sc-domain:example.com` for a domain property,
   `https://www.example.com/` for a URL-prefix property. Without `--start` / `--end` the tool fetches the 16
   months the API keeps, up to three days ago. `fetch` writes `pages.csv` (dimensions `date, page`) and
   `queries.csv` (`date, page, query`).

2. **The BigQuery bulk export**: export `searchdata_url_impression` with `data_date`, `url`, `query`, `clicks`,
   `impressions` and `sum_position` to CSV.

3. **Any tool that can export date + page rows** (Looker Studio, Sheets add-ons, SEO suites). Column names are
   recognised case-insensitively; see `src/content_decay_finder/loader.py` for the list.

A file with a `query` column is treated as query-level data. Page totals should come from a file without queries,
because Search Console leaves anonymised queries out of query-level rows; if there is only query-level data, page
totals are summed from it and the report says they are an underestimate.

## Usage

```text
content-decay-finder analyze [INPUT ...] [options]
content-decay-finder fetch --site-url SITE [options]
content-decay-finder compare OLD.json NEW.json [-f text|markdown|json] [-o FILE] [--fail-on-new N]

analyze:
  INPUT                      CSV files or directories (or use --site-url to read from the API)
  --config FILE              TOML settings ([analysis] table)
  -f, --format FMT           csv, json, markdown (md), html or all; repeatable or comma-separated
  -o, --output-dir DIR       where reports go (default content-decay-report)
  --basename NAME            report file name prefix (default content-decay)
  --fail-on-decay N          exit 1 when N or more pages are decaying
  --save-csv DIR             with --site-url: also save the fetched rows
  --quiet                    no summary on stdout
  --recent-weeks N           (4)    --baseline-weeks N (8)   --trend-weeks N (16)
  --decline-threshold X      (0.2)  --min-clicks N (30)      --seasonality auto|page|site|off
  --section-depth N          (1)    --section NAME=REGEX     --ignore REGEX
  --opp-min-position X       (8)    --opp-max-position X (20) --opp-min-impressions N (100)
  --keep-query-strings       treat /page?a=b as its own page   --top N (50 rows per table)
  --redirects CSV            redirect map (old URL -> new URL); repeatable, see "Redirect maps"

Search Console API (analyze and fetch):
  --site-url SITE            sc-domain:example.com or https://www.example.com/
  --credentials FILE         service account JSON (or GOOGLE_APPLICATION_CREDENTIALS)
  --access-token-env VAR     use an OAuth access token from VAR instead (e.g. gcloud auth print-access-token)
  --start / --end DATE       YYYY-MM-DD (Pacific Time, as Search Console reports)
  --search-type TYPE         web (default), image, video, news, discover, googleNews
  --filter EXPR              page~/blog/  query!~brand  page^REGEX  page!^REGEX  country=bgd  device!=MOBILE
  --data-state final|all     final (default) or include fresh, not yet final data
  --chunk-days N             days per request window (default 7)
  --no-queries               skip the date+page+query request (no cannibalisation)
```

Exit codes: `0` success, `1` `--fail-on-decay` or `--fail-on-new` threshold reached, `2` usage, input or API error.

Examples:

```bash
# Everything, from CSV
content-decay-finder analyze gsc-data -f all -o report

# Only the blog, two-level sections, a stricter threshold
content-decay-finder analyze gsc-data --ignore '^https://www\.example\.com/(tag|author)/' \
  --section-depth 2 --decline-threshold 0.3 -f html

# Straight from the API, keeping a copy of the data
content-decay-finder analyze --site-url sc-domain:example.com --credentials gsc.json \
  --filter 'page~/blog/' --save-csv gsc-data -f markdown

# After a migration: count the old URLs' clicks for the pages they redirect to
content-decay-finder analyze gsc-data --redirects redirects.csv -f html

# A monthly CI job that fails when five or more pages are decaying
content-decay-finder analyze gsc-data --fail-on-decay 5 -f markdown
```

## How it works

**Weeks and windows.** Rows are summed per page and ISO week (Monday to Sunday); position is the
impression-weighted average. Incomplete weeks at either end are dropped, so a week Search Console has not finished
processing does not look like a drop. Counting back from the last full week:

```text
... | baseline (8 weeks) | recent (4 weeks) |
          | trend window (16 weeks)         |
```

**Period comparison.** Weekly averages of the recent window against the baseline for clicks, impressions, CTR and
position.

**Seasonality.** With at least `recent + baseline + 52` full weeks, the same two windows 52 weeks earlier give
the change that is normal for the season: `factor = last year's recent / last year's baseline` (weekly averages,
clamped to 0.25-4). The expected recent clicks are `baseline × factor`, and the *adjusted change* compares the
recent clicks with that expectation. `--seasonality page` uses the page's own history, `site` the whole site's,
and `auto` (the default) the lower of the two, because a page's own ratio also contains its long-term growth: a
page that doubled last year would otherwise be expected to double again. Pages with fewer than 30 clicks in last
year's baseline fall back to the site factor.

**Trend.** Ordinary least squares over the weekly clicks of the trend window. The slope is divided by the
window's average (the share of its traffic a page loses per week) and multiplied by R², so a noisy series with a
slope that fits poorly counts for little: `steepness = max(0, -slope / mean) × R²`.

**Status.**

| Status | Rule |
| ------ | ---- |
| `low-data` | fewer than `min_baseline_clicks` (30) clicks in the baseline window |
| `new` | first impressions in the second half of the baseline window or later |
| `decaying` | adjusted change ≤ -20% and a downward trend (steepness > 0) |
| `watch` | adjusted change ≤ -10%, or a negative change with a clear downward trend (> 2% per week, R² ≥ 0.5) |
| `growing` | adjusted change ≥ +20% |
| `stable` | everything else |

**Causes** (for `decaying` and `watch` pages): `position` when the average position got at least 1.0 worse,
`impressions` when impressions dropped by the decline threshold, `ctr` when CTR dropped by the threshold while the
position held (a SERP feature or answer box, a competitor's better title), `seasonal` when the seasonal factor
predicts a dip.

**Refresh priority.** For `decaying` and `watch` pages:

```text
lost clicks         = max(0, expected weekly clicks - recent weekly clicks) × recent weeks
priority (raw)      = lost clicks × steepness × impressions in the recent window
priority (0-100)    = 100 × log(1 + raw) / log(1 + highest raw)
```

Lost clicks say how much traffic is at stake, steepness says the decline is real and ongoing rather than a blip,
and current impressions say Google still shows the page, so a refresh has something to work with. The log scale
keeps the ranking readable when raw values span several orders of magnitude.

**Sections.** By default the first path segment (`/blog/`, `/services/`); pages directly below the root belong to
`/`. `--section-depth 2` gives `/blog/2026/`; `--section 'Guides=^/(guides|how-to)/'` names a group (rules are
checked in order before the depth rule).

**Cannibalisation.** For each query with at least 100 impressions over the baseline and recent windows, pages
with at least 10% of its impressions compete. The query is flagged when two or more pages compete and the
leading page (most clicks in a week) changed at least twice week to week, or the leader of the baseline window is
not the leader of the recent window.

**Almost page 1.** Pages and page + query pairs with an average position between 8 and 20 and at least 100
impressions in the recent window. The estimated extra clicks are `impressions × (CTR at position 3 - current
CTR)`. The CTR curve comes from the site's own data per rounded position (1 to 10, where a position has at least
500 impressions), filled in from a generic curve where data is thin and forced to decrease with position.

## Configuration

Every setting has a command-line flag; a TOML file is handy for the rest and for sharing settings between runs
(`--config`, flags win). See [`examples/content-decay.toml`](examples/content-decay.toml):

```toml
[analysis]
recent_weeks = 4
baseline_weeks = 8
trend_weeks = 16
decline_threshold = 0.20
watch_threshold = 0.10
growth_threshold = 0.20
min_baseline_clicks = 30
position_drop = 1.0
seasonality = "auto"
min_seasonal_clicks = 30
section_depth = 1
opportunity_min_position = 8
opportunity_max_position = 20
opportunity_min_impressions = 100
opportunity_target_position = 3
cannibal_min_impressions = 100
cannibal_min_share = 0.10
cannibal_min_switches = 2
strip_query_strings = true
top = 50
ignore = ["/tag/", "/page/\\d+/"]

[analysis.sections]
"Services" = "^/services/"
```

### Redirect maps

When pages move, Search Console reports the old and the new URL separately: the old one looks like it is
decaying (its clicks fall to zero) and the new one shows up as `new`. A redirect map fixes that by counting the
rows of each old URL for its final target before the analysis.

```csv
from,to
https://www.example.com/old-guide/,https://www.example.com/guides/widgets/
/2023/05/best-widgets/,/best-widgets/
```

- Give the file with `--redirects redirects.csv` (repeatable), `redirects_file = "redirects.csv"` (a path or a
  list, relative to the TOML file) or as an inline `[analysis.redirects]` table:

  ```toml
  [analysis.redirects]
  "/old-guide/" = "/guides/widgets/"
  ```

- Entries are full `http(s)` URLs or paths starting with `/`. A path matches on any host, and a path target keeps
  the host of the URL being redirected. URLs are normalised like the data (lower-cased scheme and host, no
  fragment, no query string unless `--keep-query-strings`).
- The header is optional. Besides `from`/`to`, the columns of common exports are recognised: `Source`/`Target`,
  `Old URL`/`New URL`, `Address`/`Redirect URL` (Screaming Frog), `Source URL`/`Destination` and `Final Address`.
  When a status column is present (`Status Code`, `Type`, ...), only rows with 301, 302, 303, 307 or 308 are used.
  Comma, semicolon and tab separated files work; lines starting with `#` are comments.
- Chains (`/a` -> `/b` -> `/c`) are followed to the end. Loops, chains longer than 20 hops and two different
  targets for the same URL are errors (exit code 2), so a broken map never silently skews the report.
- `ignore` patterns are matched against the URL after redirects.
- Merged pages list their old URLs in `merged_from` (JSON and the pages CSV) and in the Markdown and HTML tables;
  the JSON `data.redirects` object has the number of rules and merged URLs.

### URL normalisation

Query strings and fragments are removed from URLs by default (`/post/?utm_source=x` and `/post/` are one page),
and scheme and host are lower-cased.

## Reports

| Format | Files | Content |
| ------ | ----- | ------- |
| `csv` | `content-decay-pages.csv`, `-sections.csv`, `-almost-page-one.csv`, `-cannibalization.csv` | every page with all metrics; one row per section, opportunity and competing page |
| `json` | `content-decay.json` | everything, including the weekly series, windows, notes and the CTR curve |
| `markdown` | `content-decay.md` | the tables, for a pull request, a ticket or a GitHub job summary |
| `html` | `content-decay.html` | a single page with sparklines for clicks, impressions and position per page and section; light and dark mode |

The JSON top-level keys are `data`, `settings` (including `top`, the row limit per table), `notes`, `site`, `refresh_priorities`, `sections`,
`cannibalization`, `almost_page_one`, `almost_page_one_queries` and `ctr_curve`. Text cells in the CSV files that
start with `=`, `+`, `-` or `@` are prefixed with `'` so spreadsheets do not run them as formulas.

### Comparing two runs

Keep the JSON report of every scheduled run and compare the latest with the previous one to see what changed:

```console
$ content-decay-finder compare reports/2026-10.json reports/2026-11.json
old: 2025-06-02 to 2026-10-04
new: 2025-07-07 to 2026-11-08
site clicks after seasonality: -5% -> -9%, lost clicks 867 -> 1,240
pages: 2 new, 1 worse, 0 better, 1 resolved, 3 unchanged

Newly flagged:
  https://www.example.com/blog/pricing-guide/  (decaying, priority 88.0, lost 310 clicks)
  ...
```

Pages are compared by their status in `refresh_priorities` (decaying and watch pages):

| Change | Meaning |
| ------ | ------- |
| `new` | flagged now, not in the old report |
| `worse` | went from `watch` to `decaying` |
| `better` | went from `decaying` to `watch` |
| `resolved` | in the old report, no longer flagged |
| `unchanged` | same status in both (the priority change is shown) |

`-f markdown` writes tables for a job summary or a ticket, `-f json` the full comparison. `--fail-on-new N` exits
with `1` when `N` or more pages are `new` or `worse`, so a monthly job can fail only on new problems instead of on
every page that is still decaying. A report lists at most `--top` flagged pages; when the new report's list is
full, a page shown as resolved may only have ranked lower, and the output says so.

## Library use

```python
from pathlib import Path

from content_decay_finder import AnalysisConfig, analyze, load_paths
from content_decay_finder.report import render_html

result = analyze(load_paths([Path("gsc-data")]), AnalysisConfig(recent_weeks=6))
for page in result.ranked()[:10]:
    print(round(page.priority), page.page, page.causes)
Path("report.html").write_text(render_html(result))
```

`SearchAnalyticsClient` in `content_decay_finder.gsc_api` can be used on its own to page through any Search
Analytics query.

## Examples

`examples/` contains:

- `sample-data/`: 70 weeks of synthetic data for `www.example.com` (`pages.csv.gz`, `queries.csv.gz`) with a
  decaying guide, a CTR drop, a seasonal page, a new page, a cannibalised query and page-2 pages
- `make_sample_data.py`: the deterministic generator of that data
- `content-decay.toml`: a commented config with named sections and ignore patterns
- `library_usage.py`: library use on the sample data
- `github-actions-monthly-report.yml`: a scheduled workflow that pulls data from the API with a service account
  secret and puts the Markdown report in the job summary

```bash
content-decay-finder analyze examples/sample-data --config examples/content-decay.toml -f all -o report
```

## Testing

```console
$ python -m venv .venv && . .venv/bin/activate
$ pip install -e ".[dev]"
$ pytest
$ ruff check . && ruff format --check .
```

The tests use fixture CSV files in several export formats and synthetic datasets with known patterns (a linear
decay, a CTR drop, a yearly seasonal dip, an alternating query leader), and a mocked transport that answers like
the OAuth token endpoint and the Search Analytics API (pagination by `startRow`, 429/503 retries, 403 errors). The
service account JWT is signed with a throwaway RSA key and its signature verified. Nothing uses the network. CI
runs the suite on Python 3.10 to 3.13, plus a smoke test of the CLI on the sample data and a Docker build.

## Security notes

- The tool only needs the read-only scope (`https://www.googleapis.com/auth/webmasters.readonly`). Give the
  service account the "Restricted" permission in Search Console, not "Owner".
- Keep the JSON key outside the repository (the `.gitignore` excludes common names) and readable only by you;
  in CI, store it as a secret and write it to a temporary file with `umask 077`, as the example workflow does.
  `--access-token-env` avoids key files altogether with a short-lived token.
- Keys and tokens are never logged or written to reports; `ServiceAccount` hides the private key in its `repr`.
- Reports contain your URLs, queries and traffic numbers. Treat them as internal data.
- The HTML report escapes every value from the data, contains no scripts and loads nothing from the network; it
  carries `<meta name="robots" content="noindex">` in case it ends up on a web server.
- CSV reports neutralise spreadsheet formulas in text cells.

## Limitations

- Search Console data is sampled and anonymised: query-level rows do not add up to page totals, and very small
  pages may have gaps. Rare queries are missing from query-level data entirely.
- Dates are Pacific Time, as Search Console reports them; weeks follow those dates.
- The API keeps about 16 months of data. That is just enough for the year-over-year adjustment with the default
  windows (64 full weeks); longer windows need a longer history, so keep your `fetch` output over time.
- Very large properties can exceed the API's per-day row limits for `date, page, query`; narrow the request with
  `--filter` or skip it with `--no-queries`.
- Position is an average over all impressions; a page ranking for many queries can "lose position" because it
  gained impressions for new, weaker queries. Check the `impressions` cause next to it.
- The seasonal adjustment is a ratio of two windows, not a full seasonal decomposition; holidays that move
  between years (Easter, Eid, Black Friday) shift by up to a few weeks.
- URL changes and redirects are not detected automatically: without a [redirect map](#redirect-maps) a migrated
  page shows as a decaying old URL and a new URL. The map is applied to the whole history, so give it only
  permanent moves.
- The generic CTR curve used where the site has little data is a rough approximation, and the "extra clicks" of
  the almost-page-1 list are an estimate, not a forecast.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and
guidelines, [SECURITY.md](SECURITY.md) for reporting vulnerabilities and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
for the code of conduct.

## License

[MIT](LICENSE), Copyright (c) 2026 Saizul Amin.
