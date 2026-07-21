"""Client-layer tests — no network. Cover the retry/decoding edge cases the
adversarial review flagged."""
from __future__ import annotations

from types import SimpleNamespace

from citeguard.clients import _host, _retry_after_seconds, _openalex_record


def test_host():
    assert _host("https://api.crossref.org/works/10.1/x") == "api.crossref.org"


def test_retry_after_numeric_vs_httpdate():
    numeric = SimpleNamespace(headers={"Retry-After": "120"})
    assert _retry_after_seconds(numeric) == 120.0
    # RFC-7231 HTTP-date form must NOT raise — return None so caller backs off.
    httpdate = SimpleNamespace(headers={"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"})
    assert _retry_after_seconds(httpdate) is None
    assert _retry_after_seconds(SimpleNamespace(headers={})) is None


def test_openalex_record_tolerates_null_author():
    work = {
        "id": "https://openalex.org/W1",
        "display_name": "A Title",
        "publication_year": 2020,
        "authorships": [{"author": None}, {"author": {"display_name": "Jane Doe"}}],
        "primary_location": {"source": {"display_name": "J", "issn_l": "1234-5678"}},
    }
    rec = _openalex_record(work)  # must not raise on the null author
    assert rec.title == "A Title"
    assert rec.authors == ["Jane Doe"]
    assert rec.issn == "1234-5678"
