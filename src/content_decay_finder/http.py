"""A tiny HTTP interface on top of urllib so the API client can be tested with a fake transport."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from content_decay_finder._version import __version__


@dataclass
class HttpResponse:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> HttpResponse: ...


class UrllibTransport:
    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> HttpResponse:
        req = urllib.request.Request(
            url, data=body, method=method, headers={"User-Agent": f"content-decay-finder/{__version__}", **headers}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return HttpResponse(resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()})
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read(), {k.lower(): v for k, v in exc.headers.items()})
