"""Matching / confidence tests — no network."""
from __future__ import annotations

from citeguard import match
from citeguard.models import FoundRecord, Reference


def test_title_score_identical_and_different():
    assert match.title_score("Deep learning", "Deep learning") == 1.0
    assert (match.title_score("Deep learning", "A field guide to quantum teapots") or 0) < 0.4
    assert match.title_score(None, "x") is None


def test_author_score_first_author_and_overlap():
    assert match.author_score(["Yann LeCun", "Y Bengio"], ["Yann LeCun", "Geoffrey Hinton"]) is not None
    # first-author agreement present -> at least 0.5
    assert match.author_score(["LeCun, Yann"], ["Yann LeCun"]) >= 0.5
    assert match.author_score([], ["x"]) is None


def test_year_score_tolerance():
    assert match.year_score(2015, 2015) == 1.0
    assert match.year_score(2015, 2016) == 0.5
    assert match.year_score(2015, 2019) == 0.0


def test_overall_confidence_weighting_and_renormalisation():
    full = match.overall_confidence({"title": 1.0, "author": 1.0, "year": 1.0})
    assert full == 1.0
    # title-only still yields a score (weights renormalise over present fields)
    assert match.overall_confidence({"title": 0.8}) == 0.8
    assert match.overall_confidence({}) == 0.0


def test_score_reference_end_to_end():
    ref = Reference(raw="x", title="Deep learning", authors=["Yann LeCun"], year=2015)
    rec = FoundRecord(source="crossref", title="Deep learning",
                      authors=["Yann LeCun", "Geoffrey Hinton"], year=2015)
    scores = match.score_reference(ref, rec)
    assert scores["title"] == 1.0
    assert scores["year"] == 1.0
    assert match.overall_confidence(scores) > 0.9
