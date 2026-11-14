"""Google Search Console Search Analytics API client with service-account authentication.

Request and response fields follow the ``searchanalytics.query`` reference
(https://developers.google.com/webmaster-tools/v1/searchanalytics/query):

- ``POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query``
- body: ``startDate``/``endDate`` (YYYY-MM-DD, Pacific Time, inclusive), ``dimensions`` (``date``, ``page``,
  ``query``, ``country``, ``device``, ``searchAppearance``, ``hour``), ``type`` (default ``web``),
  ``dimensionFilterGroups`` (``groupType: and``; filters with ``dimension``, ``operator``, ``expression``),
  ``aggregationType`` (``auto``, ``byPage``, ``byProperty``), ``rowLimit`` (1-25,000, default 1,000), ``startRow``
  (zero-based) and ``dataState`` (``final`` by default, ``all``, ``hourly_all``)
- response: ``rows[]`` with ``keys[]`` (in dimension order), ``clicks``, ``impressions``, ``ctr`` and ``position``,
  plus ``responseAggregationType``

Authentication uses the OAuth 2.0 JWT bearer flow for service accounts
(https://developers.google.com/identity/protocols/oauth2/service-account): an RS256-signed JWT with ``iss``,
``scope``, ``aud``, ``iat`` and ``exp`` (at most one hour) is exchanged at ``https://oauth2.googleapis.com/token``
with ``grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer``. The service account's email address must be added
as a user of the Search Console property.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from content_decay_finder.http import HttpResponse, Transport, UrllibTransport
from content_decay_finder.model import Row
from content_decay_finder.urls import normalize_url

log = logging.getLogger(__name__)

API_ROOT = "https://www.googleapis.com/webmasters/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
MAX_ROW_LIMIT = 25_000
DIMENSIONS = {"date", "page", "query", "country", "device", "searchAppearance", "hour"}
SEARCH_TYPES = {"web", "image", "video", "news", "discover", "googleNews"}
OPERATORS = {"contains", "equals", "notContains", "notEquals", "includingRegex", "excludingRegex"}
DATA_STATES = {"final", "all", "hourly_all"}


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"Search Console API error {status}: {message}")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


Signer = Callable[[bytes], bytes]


def rs256_signer(private_key_pem: str) -> Signer:
    """Sign with the service account's RSA key (needs ``cryptography``: pip install "content-decay-finder[api]")."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            'service-account authentication needs the "cryptography" package: '
            'pip install "content-decay-finder[api]" (or pass an access token with --access-token-env)'
        ) from exc
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)

    def sign(message: bytes) -> bytes:
        return key.sign(message, padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr,call-arg]

    return sign


@dataclass
class ServiceAccount:
    client_email: str
    private_key: str
    private_key_id: str | None = None
    token_uri: str = TOKEN_URL

    @classmethod
    def from_file(cls, path: Path) -> ServiceAccount:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ApiError(0, f"cannot read service account key {path}: {exc}") from exc
        if data.get("type") != "service_account" or "client_email" not in data or "private_key" not in data:
            raise ApiError(0, f"{path} is not a service account key file")
        return cls(
            data["client_email"], data["private_key"], data.get("private_key_id"), data.get("token_uri", TOKEN_URL)
        )

    def __repr__(self) -> str:
        return f"ServiceAccount(client_email={self.client_email!r})"

    def assertion(self, now: float, signer: Signer, scope: str = SCOPE) -> str:
        header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
        if self.private_key_id:
            header["kid"] = self.private_key_id
        iat = int(now)
        claims = {"iss": self.client_email, "scope": scope, "aud": self.token_uri, "iat": iat, "exp": iat + 3600}
        signing_input = (
            _b64url(json.dumps(header, separators=(",", ":")).encode())
            + "."
            + _b64url(json.dumps(claims, separators=(",", ":")).encode())
        )
        return signing_input + "." + _b64url(signer(signing_input.encode("ascii")))


class TokenProvider:
    """Caches an access token and refreshes it a minute before it expires."""

    def __init__(
        self,
        account: ServiceAccount | None = None,
        transport: Transport | None = None,
        signer: Signer | None = None,
        static_token: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if account is None and static_token is None:
            raise ValueError("need a service account or an access token")
        self.account = account
        self.transport = transport or UrllibTransport()
        self._signer = signer
        self.static_token = static_token
        self.clock = clock
        self._token: str | None = None
        self._expires = 0.0

    def token(self) -> str:
        if self.static_token:
            return self.static_token
        now = self.clock()
        if self._token and now < self._expires - 60:
            return self._token
        assert self.account is not None
        signer = self._signer or rs256_signer(self.account.private_key)
        body = urlencode({"grant_type": JWT_GRANT, "assertion": self.account.assertion(now, signer)}).encode()
        resp = self.transport.request(
            "POST", self.account.token_uri, {"Content-Type": "application/x-www-form-urlencoded"}, body
        )
        data = _json(resp)
        if resp.status != 200 or "access_token" not in data:
            raise ApiError(resp.status, str(data.get("error_description") or data.get("error") or "token request"))
        self._token = str(data["access_token"])
        self._expires = now + float(data.get("expires_in", 3600))
        return self._token


def _json(resp: HttpResponse) -> dict[str, Any]:
    try:
        data = json.loads(resp.body or b"{}")
    except json.JSONDecodeError:
        return {"error": resp.body[:200].decode("utf-8", "replace")}
    return data if isinstance(data, dict) else {}


@dataclass
class Filter:
    dimension: str
    expression: str
    operator: str = "equals"

    def to_dict(self) -> dict[str, str]:
        if self.dimension not in DIMENSIONS - {"date", "hour"}:
            raise ValueError(f"cannot filter on {self.dimension!r}")
        if self.operator not in OPERATORS:
            raise ValueError(f"unknown operator {self.operator!r}")
        if len(self.expression) > 4096:
            raise ValueError("filter expression is longer than 4096 characters")
        return {"dimension": self.dimension, "operator": self.operator, "expression": self.expression}


def parse_filter(text: str) -> Filter:
    """``page~/blog/`` (contains), ``page=URL`` (equals), ``query!~brand`` (notContains), ``page^regex``
    (includingRegex), ``page!^regex`` (excludingRegex), ``country=bgd`` ..."""
    for token, operator in (
        ("!~", "notContains"),
        ("!^", "excludingRegex"),
        ("!=", "notEquals"),
        ("~", "contains"),
        ("^", "includingRegex"),
        ("=", "equals"),
    ):
        if token in text:
            dim, _, expr = text.partition(token)
            return Filter(dim.strip(), expr.strip(), operator)
    raise ValueError(f"cannot parse filter {text!r}; use e.g. page~/blog/ or query!~brand")


class SearchAnalyticsClient:
    def __init__(
        self,
        tokens: TokenProvider,
        transport: Transport | None = None,
        retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.tokens = tokens
        self.transport = transport or tokens.transport
        self.retries = retries
        self.sleep = sleep

    def _post(self, site_url: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_ROOT}/sites/{quote(site_url, safe='')}/searchAnalytics/query"
        payload = json.dumps(body).encode()
        for attempt in range(self.retries + 1):
            headers = {"Authorization": f"Bearer {self.tokens.token()}", "Content-Type": "application/json"}
            resp = self.transport.request("POST", url, headers, payload)
            if resp.status == 200:
                return _json(resp)
            data = _json(resp)
            message = str(
                data.get("error", {}).get("message")
                if isinstance(data.get("error"), dict)
                else data.get("error", "request failed")
            )
            if resp.status in (429, 500, 502, 503, 504) and attempt < self.retries:
                delay = min(60.0, 2.0**attempt)
                log.warning("API answered %s, retrying in %.0fs", resp.status, delay)
                self.sleep(delay)
                continue
            if resp.status == 403:
                message += " (is the service account added as a user of this Search Console property?)"
            raise ApiError(resp.status, message)
        raise ApiError(0, "retries exhausted")  # pragma: no cover

    def query(
        self,
        site_url: str,
        start: date,
        end: date,
        dimensions: list[str],
        search_type: str = "web",
        filters: list[Filter] | None = None,
        data_state: str = "final",
        row_limit: int = MAX_ROW_LIMIT,
        aggregation_type: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every row, following ``startRow`` pagination until a page comes back short."""
        if start > end:
            raise ValueError("start date is after end date")
        unknown = set(dimensions) - DIMENSIONS
        if unknown or len(set(dimensions)) != len(dimensions):
            raise ValueError(f"bad dimensions {dimensions!r}")
        if search_type not in SEARCH_TYPES:
            raise ValueError(f"unknown search type {search_type!r}")
        if data_state not in DATA_STATES:
            raise ValueError(f"unknown dataState {data_state!r}")
        if not 1 <= row_limit <= MAX_ROW_LIMIT:
            raise ValueError("rowLimit must be between 1 and 25000")
        body: dict[str, Any] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "type": search_type,
            "dataState": data_state,
            "rowLimit": row_limit,
        }
        if filters:
            body["dimensionFilterGroups"] = [{"groupType": "and", "filters": [f.to_dict() for f in filters]}]
        if aggregation_type:
            body["aggregationType"] = aggregation_type
        start_row = 0
        while True:
            body["startRow"] = start_row
            rows = self._post(site_url, body).get("rows", [])
            yield from rows
            if len(rows) < row_limit:
                return
            start_row += row_limit

    def fetch_rows(
        self,
        site_url: str,
        start: date,
        end: date,
        with_query: bool,
        chunk_days: int = 7,
        **kwargs: Any,
    ) -> Iterator[Row]:
        """Fetch ``date, page`` (or ``date, page, query``) rows in date chunks and convert them to :class:`Row`."""
        dimensions = ["date", "page", "query"] if with_query else ["date", "page"]
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, chunk_start + timedelta(days=chunk_days - 1))
            log.info("fetching %s to %s (%s)", chunk_start, chunk_end, ", ".join(dimensions))
            for item in self.query(site_url, chunk_start, chunk_end, dimensions, **kwargs):
                keys = item.get("keys", [])
                if len(keys) != len(dimensions):
                    continue
                yield Row(
                    date=date.fromisoformat(keys[0]),
                    page=normalize_url(keys[1], strip_query=False),
                    clicks=float(item.get("clicks", 0)),
                    impressions=float(item.get("impressions", 0)),
                    position=float(item["position"]) if "position" in item else None,
                    query=keys[2] if with_query else None,
                )
            chunk_start = chunk_end + timedelta(days=1)


def default_dates(today: date, months: int = 16, lag_days: int = 3) -> tuple[date, date]:
    """The API keeps 16 months of data; the last two or three days are usually not final yet."""
    end = today - timedelta(days=lag_days)
    start = end - timedelta(days=int(months * 30.44))
    return start, end


def make_client(
    credentials: Path | None,
    access_token_env: str | None,
    transport: Transport | None = None,
    signer: Signer | None = None,
) -> SearchAnalyticsClient:
    if access_token_env:
        token = os.environ.get(access_token_env)
        if not token:
            raise ApiError(0, f"environment variable {access_token_env} is empty")
        return SearchAnalyticsClient(TokenProvider(static_token=token, transport=transport), transport)
    path = credentials or (
        Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]) if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") else None
    )
    if path is None:
        raise ApiError(0, "pass --credentials (service account JSON) or set GOOGLE_APPLICATION_CREDENTIALS")
    account = ServiceAccount.from_file(path)
    return SearchAnalyticsClient(TokenProvider(account, transport, signer), transport)
