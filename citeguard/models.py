"""Core data types for CiteGuard.

These are plain dataclasses with no third-party or ``agent_skeleton`` imports, so
the verification engine can be unit-tested and reused without the A2A stack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- Verdict statuses -------------------------------------------------------
# One authoritative status per reference. Ordered roughly most- to least-urgent
# for the human reader; RETRACTED and NOT_FOUND are the ones that must never be
# missed.
VERIFIED = "VERIFIED"            # resolved to a real record and metadata agrees
LIKELY_MATCH = "LIKELY_MATCH"    # a good query match, but confirm before trusting
MISMATCH = "MISMATCH"            # identifier resolves, but to a *different* work
RETRACTED = "RETRACTED"          # resolved AND flagged retracted by >=1 source
NOT_FOUND = "NOT_FOUND"          # no authoritative record found (possible fabrication)
UNVERIFIABLE = "UNVERIFIABLE"    # grey literature we cannot confirm via these APIs
LOOKUP_ERROR = "LOOKUP_ERROR"    # every source errored — verify manually

ALL_STATUSES = [
    RETRACTED, NOT_FOUND, MISMATCH, LIKELY_MATCH, UNVERIFIABLE, LOOKUP_ERROR, VERIFIED,
]

# Entry types we treat as "grey literature" — books, theses, reports, datasets,
# etc. are legitimately often absent from Crossref/OpenAlex/PubMed, so a no-hit
# for these is UNVERIFIABLE (not a fabrication signal).
GREY_LITERATURE_TYPES = {
    "book", "inbook", "incollection", "booklet", "manual", "mastersthesis",
    "phdthesis", "thesis", "techreport", "report", "unpublished", "misc",
    "dataset", "software", "standard", "patent",
}


@dataclass
class Reference:
    """A single citation as the *user* supplied it (before verification)."""

    raw: str
    key: str | None = None            # bib key / list index label, for reporting
    entry_type: str | None = None     # article, book, inproceedings, misc, ...
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    source_format: str | None = None  # bib | ris | docx | text

    @property
    def label(self) -> str:
        return self.key or (self.title[:60] if self.title else self.raw[:60]) or "(reference)"

    @property
    def is_grey_literature(self) -> bool:
        return (self.entry_type or "").lower() in GREY_LITERATURE_TYPES

    @property
    def has_identifier(self) -> bool:
        return bool(self.doi or self.pmid or self.arxiv_id)


@dataclass
class FoundRecord:
    """A canonical record returned by an authoritative API."""

    source: str                       # crossref | openalex | pubmed
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    container: str | None = None      # journal / venue
    issn: str | None = None           # journal ISSN (for a reliable DOAJ lookup)
    doi: str | None = None
    url: str | None = None            # clickable canonical record
    is_retracted: bool = False
    retraction_sources: list[str] = field(default_factory=list)
    oa_url: str | None = None         # open-access full text, if any
    doaj_listed: bool | None = None   # venue listed in DOAJ (open-access) — positive signal only
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Verdict:
    """The result of verifying one Reference."""

    reference: Reference
    status: str
    confidence: float                 # 0..1
    record: FoundRecord | None = None
    scores: dict[str, float] = field(default_factory=dict)  # title/author/year/container
    notes: list[str] = field(default_factory=list)
    sources_checked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        rec = self.record
        return {
            "label": self.reference.label,
            "status": self.status,
            "confidence": round(self.confidence, 3),
            "input": {
                "raw": self.reference.raw,
                "doi": self.reference.doi,
                "pmid": self.reference.pmid,
                "arxiv_id": self.reference.arxiv_id,
                "title": self.reference.title,
                "authors": self.reference.authors,
                "year": self.reference.year,
                "entry_type": self.reference.entry_type,
            },
            "matched_record": None if rec is None else {
                "source": rec.source,
                "title": rec.title,
                "authors": rec.authors,
                "year": rec.year,
                "container": rec.container,
                "issn": rec.issn,
                "doi": rec.doi,
                "url": rec.url,
                "is_retracted": rec.is_retracted,
                "retraction_sources": rec.retraction_sources,
                "open_access_url": rec.oa_url,
                "doaj_listed": rec.doaj_listed,
            },
            "match_scores": {k: round(v, 3) for k, v in self.scores.items()},
            "sources_checked": self.sources_checked,
            "notes": self.notes,
        }


@dataclass
class VerificationReport:
    """The full result over a bibliography."""

    verdicts: list[Verdict] = field(default_factory=list)
    truncated_from: int | None = None      # set if we capped the ref count
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in ALL_STATUSES}
        for v in self.verdicts:
            out[v.status] = out.get(v.status, 0) + 1
        out["TOTAL"] = len(self.verdicts)
        return out
