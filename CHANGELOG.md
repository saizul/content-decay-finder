# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
