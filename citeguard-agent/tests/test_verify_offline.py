"""Verdict-classification tests with a fake client — fully offline, deterministic.

These pin the trust/safety-critical logic: retraction dominates, an identifier
that resolves to a different title is a MISMATCH (not VERIFIED), a missing record
is NOT_FOUND for articles but UNVERIFIABLE for grey literature, and a transport
error is never reported as "not found".
"""
from __future__ import annotations

from citeguard.models import (
    LIKELY_MATCH, LOOKUP_ERROR, MISMATCH, NOT_FOUND, RETRACTED, UNVERIFIABLE,
    VERIFIED, FoundRecord, Reference,
)
from citeguard.verify import VerifyConfig, verify_one
from citeguard.clients import ClientConfig


class FakeClients:
    """Stands in for BiblioClients. Configure what each lookup returns."""

    def __init__(self, *, by_doi=None, by_pmid=None, oa_by_doi=None,
                 query=None, notes=None):
        self._by_doi = by_doi or {}
        self._by_pmid = by_pmid or {}
        self._oa_by_doi = oa_by_doi or {}
        self._query = query or []
        self.notes = list(notes or [])

    def crossref_by_doi(self, doi):
        return self._by_doi.get(doi)

    def openalex_by_doi(self, doi):
        return self._oa_by_doi.get(doi)

    def pubmed_by_pmid(self, pmid):
        return self._by_pmid.get(pmid)

    def openalex_by_pmid(self, pmid):
        return None

    def openalex_search(self, title):
        return None

    def arxiv_by_id(self, arxiv_id):
        return self._by_doi.get("arxiv:" + arxiv_id)

    def crossref_by_query(self, *, bibliographic, author=None, rows=5):
        return list(self._query)

    def unpaywall_oa(self, doi):
        return None


CFG = VerifyConfig(client=ClientConfig(), check_open_access=False)


def _v(ref, clients):
    return verify_one(ref, clients, CFG)


def test_verified_by_doi():
    doi = "10.1126/science.1225829"
    rec = FoundRecord(source="crossref", title="A Programmable Dual-RNA Guided DNA Endonuclease",
                      authors=["Martin Jinek"], year=2012, doi=doi, url="https://doi.org/" + doi)
    ref = Reference(raw="x", doi=doi, entry_type="article",
                    title="A Programmable Dual-RNA Guided DNA Endonuclease",
                    authors=["Jinek, M"], year=2012)
    v = _v(ref, FakeClients(by_doi={doi: rec}, oa_by_doi={doi: rec}))
    assert v.status == VERIFIED
    assert v.confidence >= 0.85


def test_retracted_dominates_even_with_good_match():
    doi = "10.1016/s0140-6736(97)11096-0"
    cr = FoundRecord(source="crossref", title="Ileal-lymphoid-nodular hyperplasia",
                     authors=["A J Wakefield"], year=1998, doi=doi)
    oa = FoundRecord(source="openalex", title="Ileal-lymphoid-nodular hyperplasia",
                     year=1998, doi=doi, is_retracted=True,
                     retraction_sources=["openalex:is_retracted"])
    ref = Reference(raw="x", doi=doi, entry_type="article",
                    title="Ileal-lymphoid-nodular hyperplasia", year=1998)
    v = _v(ref, FakeClients(by_doi={doi: cr}, oa_by_doi={doi: oa}))
    assert v.status == RETRACTED
    assert "openalex:is_retracted" in v.record.retraction_sources


def test_identifier_resolves_to_different_title_is_mismatch():
    doi = "10.1038/nature14539"
    rec = FoundRecord(source="crossref", title="Deep learning",
                      authors=["Yann LeCun"], year=2015, doi=doi)
    ref = Reference(raw="x", doi=doi, entry_type="article",
                    title="A Field Guide to Ambient Quantum Teapots", year=2015)
    v = _v(ref, FakeClients(by_doi={doi: rec}, oa_by_doi={doi: rec}))
    assert v.status == MISMATCH


def test_missing_article_is_not_found():
    ref = Reference(raw="Totally made up paper", doi="10.1234/jfake.2023.99999",
                    entry_type="article", title="Totally made up paper")
    v = _v(ref, FakeClients())
    assert v.status == NOT_FOUND


def test_missing_book_is_unverifiable():
    ref = Reference(raw="Some textbook", entry_type="book",
                    title="Introduction to Algorithms")
    v = _v(ref, FakeClients())
    assert v.status == UNVERIFIABLE


def test_transport_error_is_lookup_error_not_not_found():
    ref = Reference(raw="x", doi="10.9999/unreachable", entry_type="article", title="x")
    clients = FakeClients(notes=["request to api.crossref.org failed: ConnectionError"])
    v = _v(ref, clients)
    assert v.status == LOOKUP_ERROR


def test_arxiv_resolved_authoritatively_not_fuzzy():
    rec = FoundRecord(source="arxiv", title="Attention Is All You Need",
                      authors=["Ashish Vaswani"], year=2017,
                      url="https://arxiv.org/abs/1706.03762")
    ref = Reference(raw="x", arxiv_id="1706.03762", entry_type="article",
                    title="Attention is all you need", year=2017)
    v = _v(ref, FakeClients(by_doi={"arxiv:1706.03762": rec}))
    assert v.status == VERIFIED
    assert v.record.source == "arxiv"


def test_arxiv_nonexistent_id_is_not_found():
    ref = Reference(raw="x", arxiv_id="9999.99999", entry_type="article", title="Nope")
    v = _v(ref, FakeClients())
    assert v.status == NOT_FOUND


def test_weak_query_match_to_retracted_is_not_flagged_retracted():
    # A retracted record that is only a POOR fuzzy hit must not be reported
    # RETRACTED (that would misattribute a retraction to the wrong work), and
    # the confidence must not be coerced to 1.0.
    cand = FoundRecord(source="openalex", title="Some Unrelated Retracted Paper on Widgets",
                       year=2010, doi="10.1/x", is_retracted=True,
                       retraction_sources=["openalex:is_retracted"])
    ref = Reference(raw="A completely different made-up title", entry_type="article",
                    title="A completely different made-up title", year=2020)
    v = _v(ref, FakeClients(query=[cand], oa_by_doi={"10.1/x": cand}))
    assert v.status == NOT_FOUND
    assert v.status != RETRACTED
    assert v.confidence < 1.0


def test_partial_source_failure_is_lookup_error_not_not_found():
    # Crossref errored (a note recorded) but OpenAlex returned a weak candidate;
    # we must not brand the reference NOT_FOUND when a source was never reached.
    cand = FoundRecord(source="openalex", title="Unrelated", year=2000, doi="10.1/y")
    ref = Reference(raw="My real paper title here", entry_type="article",
                    title="My real paper title here", year=2021)
    clients = FakeClients(query=[cand], notes=["request to api.crossref.org failed: HTTP 429"])
    v = _v(ref, clients)
    assert v.status == LOOKUP_ERROR


def test_query_match_requires_multifield_agreement():
    cand = FoundRecord(source="crossref", title="Attention is all you need",
                       authors=["Ashish Vaswani"], year=2017, doi="10.5555/aiayn")
    # Strong title + matching year -> VERIFIED.
    ref_ok = Reference(raw="x", entry_type="article",
                       title="Attention is all you need", authors=["Vaswani, A"], year=2017)
    v_ok = _v(ref_ok, FakeClients(query=[cand], oa_by_doi={"10.5555/aiayn": cand}))
    assert v_ok.status == VERIFIED
    # Same title but wrong year and no author overlap -> only LIKELY_MATCH.
    ref_weak = Reference(raw="x", entry_type="article",
                         title="Attention is all you need", year=1990)
    v_weak = _v(ref_weak, FakeClients(query=[cand], oa_by_doi={"10.5555/aiayn": cand}))
    assert v_weak.status == LIKELY_MATCH
