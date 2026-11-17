"""Redirect maps: merge the history of moved URLs into the page they redirect to.

Without a map, a migrated page shows up twice: the old URL as "decaying" (its clicks fall to zero) and the new URL
as "new" or "growing". With a map, rows of the old URL are counted for the final target before the analysis, so the
page is judged on its whole history.

Maps come from a CSV file (``from,to``; exports of Screaming Frog, the WordPress Redirection plugin, Rank Math and
Yoast use other column names, which are recognised as aliases) or from a ``[analysis.redirects]`` table in the
TOML configuration. Entries may be full URLs or paths: ``/old/`` matches that path on any host.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from content_decay_finder.model import Row
from content_decay_finder.urls import normalize_url

MAX_HOPS = 20
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

FROM_ALIASES = frozenset(
    {
        "from",
        "source",
        "source url",
        "source_url",
        "old",
        "old url",
        "old_url",
        "address",
        "url",
        "redirect from",
        "origin",
    }
)
TO_ALIASES = frozenset(
    {
        "to",
        "target",
        "target url",
        "target_url",
        "new",
        "new url",
        "new_url",
        "destination",
        "destination url",
        "redirect url",
        "redirect uri",
        "redirect to",
        "final address",
    }
)
STATUS_ALIASES = frozenset({"status", "status code", "status_code", "code", "type", "http code", "action code"})


class RedirectError(ValueError):
    """A bad redirect map: unreadable file, missing columns or a redirect loop."""


def _is_path(entry: str) -> bool:
    return entry.startswith("/")


def _normalize(entry: str, strip_query: bool) -> str:
    entry = entry.strip()
    if _is_path(entry):
        parts = urlsplit(entry)
        return urlunsplit(("", "", parts.path or "/", "" if strip_query else parts.query, ""))
    return normalize_url(entry, strip_query)


def _valid(entry: str) -> bool:
    if _is_path(entry):
        return True
    parts = urlsplit(entry)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


@dataclass
class RedirectMap:
    """Old URL (or path) -> new URL (or path). Chains are followed; loops are rejected by :meth:`validate`."""

    rules: dict[str, str] = field(default_factory=dict)
    strip_query: bool = True
    sources: list[str] = field(default_factory=list)
    skipped: int = 0  # rows ignored because of a non-redirect status code

    def __len__(self) -> int:
        return len(self.rules)

    def __bool__(self) -> bool:
        return bool(self.rules)

    def add(self, old: str, new: str) -> None:
        """Add one rule. Both sides must be an http(s) URL or a path starting with ``/``."""
        old_n, new_n = _normalize(old, self.strip_query), _normalize(new, self.strip_query)
        for value, raw in ((old_n, old), (new_n, new)):
            if not value or not _valid(value):
                raise RedirectError(f"redirect entries must be http(s) URLs or paths starting with '/', got {raw!r}")
        if old_n == new_n:
            return  # e.g. http -> https after normalisation of an already-https export; nothing to merge
        current = self.rules.get(old_n)
        if current is not None and current != new_n:
            raise RedirectError(f"conflicting redirects for {old_n}: {current} and {new_n}")
        self.rules[old_n] = new_n

    def update(self, pairs: Iterable[tuple[str, str]]) -> None:
        for old, new in pairs:
            self.add(old, new)

    def _step(self, url: str) -> str | None:
        target = self.rules.get(url)
        if target is not None:
            return self._absolute(target, url)
        if not _is_path(url):
            parts = urlsplit(url)
            key = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            target = self.rules.get(key)
            if target is not None:
                return self._absolute(target, url)
        return None

    @staticmethod
    def _absolute(target: str, source: str) -> str:
        """A path-only target keeps the scheme and host of the URL being redirected."""
        if _is_path(target) and not _is_path(source):
            parts = urlsplit(source)
            t = urlsplit(target)
            return urlunsplit((parts.scheme, parts.netloc, t.path, t.query, ""))
        return target

    def resolve(self, url: str) -> str:
        """The final target of ``url`` after following every hop (``url`` itself if no rule matches)."""
        seen = [url]
        current = url
        for _ in range(MAX_HOPS):
            nxt = self._step(current)
            if nxt is None or nxt == current:
                return current
            if nxt in seen:
                raise RedirectError("redirect loop: " + " -> ".join([*seen, nxt]))
            seen.append(nxt)
            current = nxt
        raise RedirectError(f"redirect chain longer than {MAX_HOPS} hops starting at {url}")

    def validate(self) -> None:
        """Raise :class:`RedirectError` if any rule is part of a loop or an over-long chain."""
        for old in self.rules:
            self.resolve(old)

    def apply(self, rows: Iterable[Row]) -> tuple[list[Row], dict[str, set[str]]]:
        """Rewrite each row's page to its final target.

        Returns the new rows and, for every target that received data, the set of old URLs merged into it.
        """
        cache: dict[str, str] = {}
        merged: dict[str, set[str]] = {}
        out: list[Row] = []
        for row in rows:
            target = cache.get(row.page)
            if target is None:
                target = cache[row.page] = self.resolve(row.page)
            if target != row.page:
                merged.setdefault(target, set()).add(row.page)
                row = replace(row, page=target)
            out.append(row)
        return out, merged


def _header_index(header: list[str], aliases: frozenset[str]) -> int | None:
    for idx, name in enumerate(header):
        if name.replace("﻿", "").strip().strip('"').lower() in aliases:
            return idx
    return None


def _dialect(sample: str) -> type[csv.Dialect] | csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _status_ok(value: str) -> bool:
    """True for redirect status codes and for anything that is not a number (e.g. "redirect")."""
    value = value.strip()
    if not value.isdigit():
        return True
    return int(value) in REDIRECT_STATUSES


def iter_redirect_pairs(text: str, source: str = "<redirects>") -> Iterator[tuple[str, str, bool]]:
    """Yield ``(old, new, keep)`` from CSV text. ``keep`` is False for rows whose status is not a redirect.

    A header row is optional: without one, the first two columns are old and new URL.
    """
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return
    reader = csv.reader(io.StringIO("\n".join(lines)), _dialect("\n".join(lines[:20])))
    rows = list(reader)
    first = rows[0]
    first_cell = first[0].replace("﻿", "").strip() if first else ""
    if first_cell.startswith(("/", "http://", "https://")):
        old_i, new_i, status_i, body, start = 0, 1, None, rows, 1
    else:
        old_i = _header_index(first, FROM_ALIASES)
        new_i = _header_index(first, TO_ALIASES)
        status_i = _header_index(first, STATUS_ALIASES)
        if old_i is None or new_i is None:
            raise RedirectError(
                f"{source}: need a 'from' and a 'to' column (or a file without a header); found {', '.join(first)}"
            )
        body, start = rows[1:], 2
    for line_no, record in enumerate(body, start):
        if not any(cell.strip() for cell in record):
            continue
        if max(old_i, new_i) >= len(record):
            raise RedirectError(f"{source}:{line_no}: expected at least {max(old_i, new_i) + 1} columns")
        old, new = record[old_i].strip(), record[new_i].strip()
        if not old or not new:
            continue  # e.g. a 404 row in a crawl export without a target
        keep = status_i is None or status_i >= len(record) or _status_ok(record[status_i])
        yield old, new, keep


def load_redirects(paths: Iterable[Path], strip_query: bool = True, into: RedirectMap | None = None) -> RedirectMap:
    """Read one or more redirect CSV files into a (new or existing) :class:`RedirectMap` and validate it."""
    rmap = into if into is not None else RedirectMap(strip_query=strip_query)
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError as exc:
            raise RedirectError(f"redirect map not found: {path}") from exc
        except UnicodeDecodeError as exc:
            raise RedirectError(f"{path}: not UTF-8 text") from exc
        for old, new, keep in iter_redirect_pairs(text, str(path)):
            if keep:
                try:
                    rmap.add(old, new)
                except RedirectError as exc:
                    raise RedirectError(f"{path}: {exc}") from exc
            else:
                rmap.skipped += 1
        rmap.sources.append(str(path))
    rmap.validate()
    return rmap


__all__ = ["RedirectError", "RedirectMap", "iter_redirect_pairs", "load_redirects"]
