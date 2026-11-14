import base64
import json
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from content_decay_finder.gsc_api import (
    ApiError,
    Filter,
    SearchAnalyticsClient,
    ServiceAccount,
    TokenProvider,
    default_dates,
    make_client,
    parse_filter,
    rs256_signer,
)
from fake_api import FakeGoogle


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def key_file(tmp_path: Path, rsa_key) -> Path:
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    path = tmp_path / "sa.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "client_email": "reader@proj.iam.gserviceaccount.com",
                "private_key": pem,
                "private_key_id": "kid123",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
    )
    return path


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_jwt_assertion_is_valid_rs256(key_file: Path, rsa_key):
    account = ServiceAccount.from_file(key_file)
    assertion = account.assertion(1_800_000_000, rs256_signer(account.private_key))
    header_b64, claims_b64, sig_b64 = assertion.split(".")
    header = json.loads(_b64decode(header_b64))
    claims = json.loads(_b64decode(claims_b64))
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "kid123"}
    assert claims == {
        "iss": "reader@proj.iam.gserviceaccount.com",
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": 1_800_000_000,
        "exp": 1_800_003_600,
    }
    rsa_key.public_key().verify(
        _b64decode(sig_b64), f"{header_b64}.{claims_b64}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    assert "private_key" not in repr(account)


def test_token_exchange_and_caching(key_file: Path):
    fake = FakeGoogle()
    clock = [1_800_000_000.0]
    tokens = TokenProvider(ServiceAccount.from_file(key_file), fake, clock=lambda: clock[0])
    assert tokens.token() == "tok1"
    assert fake.token_requests[0]["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assert fake.token_requests[0]["assertion"][0].count(".") == 2
    clock[0] += 3000
    assert tokens.token() == "tok1"
    clock[0] += 600  # within a minute of expiry -> refresh
    assert tokens.token() == "tok2"


def test_token_error():
    class Refuse:
        def request(self, method, url, headers, body):
            from content_decay_finder.http import HttpResponse

            return HttpResponse(400, b'{"error": "invalid_grant", "error_description": "Invalid JWT Signature."}')

    account = ServiceAccount("a@b", "unused")
    with pytest.raises(ApiError, match="Invalid JWT Signature"):
        TokenProvider(account, Refuse(), signer=lambda m: b"sig").token()


def test_query_request_body_and_pagination():
    fake = FakeGoogle(rows_per_day=5, pages=2)
    client = SearchAnalyticsClient(TokenProvider(static_token="static", transport=fake), fake)
    rows = list(
        client.query(
            "sc-domain:example.com",
            date(2026, 1, 1),
            date(2026, 1, 3),
            ["date", "page", "query"],
            filters=[Filter("page", "/blog/", "contains")],
            row_limit=7,
        )
    )
    assert len(rows) == 3 * 2 * 5
    assert [q["startRow"] for q in fake.queries] == [0, 7, 14, 21, 28]
    body = fake.queries[0]
    assert body["startDate"] == "2026-01-01" and body["endDate"] == "2026-01-03"
    assert body["dimensions"] == ["date", "page", "query"]
    assert body["type"] == "web" and body["dataState"] == "final" and body["rowLimit"] == 7
    assert body["dimensionFilterGroups"] == [
        {"groupType": "and", "filters": [{"dimension": "page", "operator": "contains", "expression": "/blog/"}]}
    ]
    assert fake.sites[0] == "sc-domain:example.com"


def test_fetch_rows_chunks_dates_and_converts():
    fake = FakeGoogle(pages=1)
    client = SearchAnalyticsClient(TokenProvider(static_token="static", transport=fake), fake)
    rows = list(client.fetch_rows("https://www.example.com/", date(2026, 1, 1), date(2026, 1, 10), False, chunk_days=4))
    assert len(rows) == 10
    assert [(q["startDate"], q["endDate"]) for q in fake.queries] == [
        ("2026-01-01", "2026-01-04"),
        ("2026-01-05", "2026-01-08"),
        ("2026-01-09", "2026-01-10"),
    ]
    assert rows[0].page == "https://www.example.com/p0" and rows[0].position == 4.5 and rows[0].query is None
    qrows = list(client.fetch_rows("https://www.example.com/", date(2026, 1, 1), date(2026, 1, 1), True))
    assert {r.query for r in qrows} == {"query 0", "query 1", "query 2"}


def test_retries_then_error_hint():
    fake = FakeGoogle()
    slept: list[float] = []
    client = SearchAnalyticsClient(TokenProvider(static_token="static", transport=fake), fake, sleep=slept.append)
    fake.fail_next = [429, 503]
    assert list(client.query("sc-domain:e.example", date(2026, 1, 1), date(2026, 1, 1), ["date"]))
    assert slept == [1.0, 2.0]
    fake.fail_next = [403]
    with pytest.raises(ApiError, match="added as a user"):
        list(client.query("sc-domain:e.example", date(2026, 1, 1), date(2026, 1, 1), ["date"]))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dimensions": ["date", "date"]},
        {"dimensions": ["url"]},
        {"search_type": "shopping"},
        {"data_state": "fresh"},
        {"row_limit": 25001},
        {"start": date(2026, 2, 1)},
    ],
)
def test_query_validation(kwargs):
    client = SearchAnalyticsClient(TokenProvider(static_token="x", transport=FakeGoogle()))
    args = {"site_url": "s", "start": date(2026, 1, 1), "end": date(2026, 1, 2), "dimensions": ["date"]} | kwargs
    with pytest.raises(ValueError):
        list(client.query(**args))


def test_parse_filter():
    assert parse_filter("page~/blog/") == Filter("page", "/blog/", "contains")
    assert parse_filter("query!~brand") == Filter("query", "brand", "notContains")
    assert parse_filter("page^/(a|b)/") == Filter("page", "/(a|b)/", "includingRegex")
    assert parse_filter("page!^/tag/") == Filter("page", "/tag/", "excludingRegex")
    assert parse_filter("country=bgd") == Filter("country", "bgd", "equals")
    assert parse_filter("device!=MOBILE") == Filter("device", "MOBILE", "notEquals")
    with pytest.raises(ValueError):
        parse_filter("nothing")
    with pytest.raises(ValueError):
        Filter("date", "x").to_dict()
    with pytest.raises(ValueError):
        Filter("page", "x" * 4097).to_dict()


def test_bad_key_files(tmp_path: Path):
    path = tmp_path / "k.json"
    path.write_text('{"type": "authorized_user"}')
    with pytest.raises(ApiError, match="not a service account"):
        ServiceAccount.from_file(path)
    path.write_text("{")
    with pytest.raises(ApiError):
        ServiceAccount.from_file(path)


def test_make_client(monkeypatch, key_file: Path):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(ApiError, match="--credentials"):
        make_client(None, None)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key_file))
    assert make_client(None, None).tokens.account.client_email.startswith("reader@")
    monkeypatch.setenv("GSC_TOKEN", "abc")
    assert make_client(None, "GSC_TOKEN").tokens.token() == "abc"
    monkeypatch.setenv("GSC_TOKEN", "")
    with pytest.raises(ApiError, match="empty"):
        make_client(None, "GSC_TOKEN")


def test_default_dates():
    start, end = default_dates(date(2026, 11, 14))
    assert end == date(2026, 11, 11)
    assert (end - start).days == 487
