"""URL normalisation and sections."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from content_decay_finder.config import SectionRule


def normalize_url(url: str, strip_query: bool = True) -> str:
    """Lower-case scheme and host, drop the fragment (and by default the query string)."""
    url = url.strip()
    parts = urlsplit(url)
    if not parts.scheme:
        return url
    path = parts.path or "/"
    query = "" if strip_query else parts.query
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def url_path(url: str) -> str:
    parts = urlsplit(url)
    return parts.path or "/" if parts.scheme else (url if url.startswith("/") else "/" + url)


def section_of(url: str, depth: int = 1, rules: list[SectionRule] | None = None) -> str:
    """The section of a page: the first ``depth`` path segments (``/blog/``), or the first matching named rule.

    Pages directly below the root (``/about``) and the home page belong to ``/``.
    """
    path = url_path(url)
    for rule in rules or []:
        if rule.pattern.search(path):
            return rule.name
    if depth == 0:
        return "/"
    segments = [s for s in path.split("/") if s]
    # the last segment is the page itself unless the URL ends with a slash
    if not path.endswith("/") and segments:
        segments = segments[:-1]
    if not segments:
        return "/"
    return "/" + "/".join(segments[:depth]) + "/"
