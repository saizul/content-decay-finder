"""A mocked transport that answers like the OAuth token endpoint and the Search Analytics API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote

from content_decay_finder.http import HttpResponse


class FakeGoogle:
    def __init__(self, rows_per_day: int = 3, pages: int = 2, row_limit_cap: int | None = None) -> None:
        self.tokens_issued = 0
        self.token_requests: list[dict[str, list[str]]] = []
        self.queries: list[dict] = []
        self.sites: list[str] = []
        self.rows_per_day = rows_per_day
        self.pages = pages
        self.fail_next: list[int] = []
        self.row_limit_cap = row_limit_cap

    def request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> HttpResponse:
        if url == "https://oauth2.googleapis.com/token":
            form = parse_qs((body or b"").decode())
            self.token_requests.append(form)
            self.tokens_issued += 1
            return HttpResponse(
                200,
                json.dumps(
                    {"access_token": f"tok{self.tokens_issued}", "expires_in": 3600, "token_type": "Bearer"}
                ).encode(),
            )
        prefix = "https://www.googleapis.com/webmasters/v3/sites/"
        assert url.startswith(prefix) and url.endswith("/searchAnalytics/query"), url
        assert headers["Authorization"].startswith("Bearer tok") or headers["Authorization"] == "Bearer static"
        if self.fail_next:
            code = self.fail_next.pop(0)
            return HttpResponse(code, json.dumps({"error": {"code": code, "message": "slow down"}}).encode())
        self.sites.append(unquote(url[len(prefix) : -len("/searchAnalytics/query")]))
        req = json.loads(body or b"{}")
        self.queries.append(req)
        rows = self._all_rows(req)
        start = req.get("startRow", 0)
        limit = req.get("rowLimit", 1000)
        page_rows = rows[start : start + limit]
        out = (
            {"rows": page_rows, "responseAggregationType": "byPage"}
            if page_rows
            else {"responseAggregationType": "byPage"}
        )
        return HttpResponse(200, json.dumps(out).encode())

    def _all_rows(self, req: dict) -> list[dict]:
        start = date.fromisoformat(req["startDate"])
        end = date.fromisoformat(req["endDate"])
        dims = req["dimensions"]
        rows = []
        day = start
        while day <= end:
            for p in range(self.pages):
                for q in range(self.rows_per_day if "query" in dims else 1):
                    keys = [day.isoformat(), f"https://www.example.com/p{p}"]
                    if "query" in dims:
                        keys.append(f"query {q}")
                    rows.append({"keys": keys, "clicks": 2.0, "impressions": 20.0, "ctr": 0.1, "position": 4.5})
            day += timedelta(days=1)
        return rows
