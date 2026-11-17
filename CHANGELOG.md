# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Redirect maps: `--redirects FILE` (repeatable), `redirects_file` and `[analysis.redirects]` in the TOML config
  merge the rows of moved URLs into the page they redirect to before the analysis, so a migrated page is no longer
  reported as a decaying old URL plus a new one. Reads `from,to` CSV files and Screaming Frog, Redirection, Rank Math
  and Yoast style exports (column aliases, status code filter, `,`/`;`/tab), follows chains and rejects loops,
  conflicting targets and chains over 20 hops.
- `merged_from` per page in the JSON and pages CSV reports and in the Markdown and HTML tables, a `data.redirects`
  summary in the JSON report and a note in every report when URLs were merged.
- `CODE_OF_CONDUCT.md`, issue templates (bug report, feature request) and a pull request template.

### Changed

- The pages CSV report has a new last column, `merged_from` (empty without a redirect map).

## [0.1.0] - 2026-11-14

### Added

- CSV loader for date + page (+ query) data: this tool's format, Looker Studio and spreadsheet exports, the
  BigQuery bulk export (`sum_position`), gzip files and directories, with column aliases and number formats such as
  `1,234` and `4.5%`.
- Search Analytics API client with service-account JWT authentication (read-only scope), date chunking,
  `startRow` pagination, retries, dimension filters, search type and `dataState`; `fetch` command to save the data
  as CSV, `--access-token-env` as an alternative to key files.
- Weekly buckets with partial weeks dropped, recent vs baseline comparison and a least-squares trend with R² for
  clicks, impressions and position.
- Year-over-year seasonality per page and per site (`auto` takes the lower factor).
- Status per page (`decaying`, `watch`, `stable`, `growing`, `new`, `low-data`) and likely causes (`position`,
  `impressions`, `ctr`, `seasonal`).
- Refresh priority: lost clicks × trend steepness × current impressions, scaled to 0-100.
- URL sections by path depth or named regular expressions.
- Cannibalisation detection for queries whose leading page changes.
- "Almost page 1" list (positions 8-20) with extra clicks estimated from the site's own CTR curve.
- CSV, JSON, Markdown and self-contained HTML reports with inline SVG sparklines; `--fail-on-decay` for CI.
- TOML configuration, synthetic sample data and its generator, Docker image published to
  `ghcr.io/saizul/content-decay-finder`.

[Unreleased]: https://github.com/saizul/content-decay-finder/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/content-decay-finder/releases/tag/v0.1.0
