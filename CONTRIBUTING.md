# Contributing

Thanks for taking the time to improve content-decay-finder. Bug reports, new
input formats, better statistics and documentation fixes are all welcome.

## Reporting a bug

Open an issue with:

- the command you ran and its output (`-vv` adds debug logging)
- your Python version and operating system
- for wrong results: a small CSV that shows the problem, with real URLs replaced
  by `example.com` and numbers changed if they are confidential; the JSON report
  (`-f json`) of that file helps
- for input format problems: the header line of the file and one data row

Never paste service account keys or access tokens.

## Development setup

You need Python 3.10 or newer. No Google account is needed for development.

```console
$ git clone https://github.com/saizul/content-decay-finder.git
$ cd content-decay-finder
$ python -m venv .venv
$ . .venv/bin/activate
$ python -m pip install -e ".[dev]"
```

Before every commit:

```console
$ ruff check .
$ ruff format --check .
$ pytest
```

All three must pass; CI runs them on Python 3.10 to 3.13.

## Guidelines

- **Tests never use the network.** Use the fixture CSV files in
  `tests/fixtures/`, the synthetic patterns in `tests/synth.py` and the mocked
  Google endpoints in `tests/fake_api.py`.
- **API details need a source.** Request and response fields follow the Search
  Analytics `query` reference; link the page when you add or change one.
- **Explain the statistics.** A change to a formula (trend, seasonality,
  priority) needs a test with a dataset where the right answer is known, and an
  update to "How it works" in the README.
- **The JSON report is a contract.** Do not rename keys without a changelog
  entry.
- **Escape everything** that comes from the data in HTML and Markdown output.
- **Every change comes with a test** that fails without it.
- Add a line to the `Unreleased` section of `CHANGELOG.md` for anything a user
  would notice.
- If you change `examples/make_sample_data.py`, run it and commit the new
  `examples/sample-data/` files.

## Project layout

```text
src/content_decay_finder/
    loader.py           CSV formats, column aliases, number and date parsing
    gsc_api.py          service-account auth and the Search Analytics client
    weekly.py           ISO-week buckets and analysis windows
    stats.py            least squares, Theil-Sen, percentage change
    seasonality.py      year-over-year factors
    decay.py            per-page status, causes and priority
    sections.py         section roll-up
    redirects.py        redirect maps (old URL -> new URL) applied before the analysis
    cannibalization.py  queries moving between pages
    opportunities.py    almost page 1 and the CTR curve
    analyze.py          runs everything, AnalysisResult
    report/             csv, json, markdown, html, sparklines
    config.py           settings and the TOML file
    cli.py              command-line interface
tests/                  pytest suite, fixtures, synthetic data, fake API
examples/               sample data and generator, config, CI workflow, library use
```

## Pull requests

- Keep each pull request focused on one change.
- Describe what changed and why, and how you tested it.
- Do not bump the version number; that happens at release time.

By contributing you agree that your work is released under the MIT License.

## Code of conduct

Everyone taking part in this project is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Be
respectful and constructive; harassment of any kind is not tolerated.
