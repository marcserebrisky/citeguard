"""Orchestrate verification of a bibliography.

For each reference: resolve an authoritative record (by identifier if we have
one, else by a Crossref bibliographic query), gather retraction signals from
every source consulted, score the metadata agreement, and assign exactly one
verdict. Never invents an identifier or a record.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import match
from .clients import BiblioClients, ClientConfig
from .models import (
    LIKELY_MATCH, LOOKUP_ERROR, MISMATCH, NOT_FOUND, RETRACTED, UNVERIFIABLE,
    VERIFIED, FoundRecord, Reference, Verdict, VerificationReport,
)

# Thresholds (documented in the README so verdicts are auditable, not magic).
T_IDENTIFIER_TITLE_OK = 0.55   # DOI resolves + title agrees at least this much
T_QUERY_VERIFIED_TITLE = 0.85  # no-identifier match strong enough to call VERIFIED
T_QUERY_LIKELY_TITLE = 0.70    # good enough to flag as a probable match
MAX_REFERENCES = 300           # hard cap; extras reported as truncated


@dataclass
class VerifyConfig:
    client: ClientConfig
    check_open_access: bool = False   # Unpaywall lookups (needs a real contact email)
    max_workers: int = 8
    max_references: int = MAX_REFERENCES


def _merge_retraction(primary: FoundRecord, *others: FoundRecord | None) -> None:
    """Fold retraction signals from secondary sources into ``primary``."""
    for rec in others:
        if rec and rec.is_retracted:
            primary.is_retracted = True
            for s in rec.retraction_sources:
                if s not in primary.retraction_sources:
                    primary.retraction_sources.append(s)


def _resolve(ref: Reference, clients: BiblioClients) -> tuple[FoundRecord | None, list[str]]:
    """Return (best record or None, sources_checked).

    Each reference is resolved with its own fresh client, so any entry in
    ``clients.notes`` afterwards means a transport error occurred *for this
    reference* — the caller uses that to tell LOOKUP_ERROR from a clean miss.
    """
    checked: list[str] = []

    # 1) By DOI — the strongest anchor. Cross-check OpenAlex for retraction.
    if ref.doi:
        cr = clients.crossref_by_doi(ref.doi)
        checked.append("crossref")
        oa = clients.openalex_by_doi(ref.doi)
        checked.append("openalex")
        primary = cr or oa
        if primary:
            _merge_retraction(primary, oa if cr else None)
            return primary, checked
        return None, checked

    # 2) By PMID — PubMed is authoritative for retraction in biomedicine.
    if ref.pmid:
        pm = clients.pubmed_by_pmid(ref.pmid)
        checked.append("pubmed")
        oa = clients.openalex_by_pmid(ref.pmid)
        checked.append("openalex")
        primary = pm or oa
        if primary:
            _merge_retraction(primary, oa if pm else None)
            return primary, checked
        return None, checked

    # 3) By arXiv id — authoritative via the arXiv API (the id IS the paper, so
    #    no fuzzy matching). A well-formed id that doesn't resolve is a miss
    #    (possible fabrication), NOT a reason to fuzzy-match a similar title.
    if ref.arxiv_id:
        rec = clients.arxiv_by_id(ref.arxiv_id)
        checked.append("arxiv")
        return rec, checked

    # 4) No identifier — Crossref bibliographic query, with an
    #    OpenAlex title search as a second source, then confirm retraction on the
    #    chosen candidate via OpenAlex.
    query_text = ref.title or ref.raw
    author = ref.authors[0] if ref.authors else None
    candidates = clients.crossref_by_query(bibliographic=query_text, author=author)
    checked.append("crossref")
    oa_cand = clients.openalex_search(query_text)
    checked.append("openalex")
    if oa_cand:
        candidates = candidates + [oa_cand]
    if not candidates:
        return None, checked
    best = max(candidates, key=lambda c: match.title_score(query_text, c.title) or 0.0)
    if best.doi:
        oa = clients.openalex_by_doi(best.doi)
        _merge_retraction(best, oa)
    return best, checked


def verify_one(ref: Reference, clients: BiblioClients, cfg: VerifyConfig) -> Verdict:
    record, checked = _resolve(ref, clients)
    notes: list[str] = []

    if record is None:
        # Fresh client per reference => any recorded note is an error for THIS ref.
        if clients.notes:
            return Verdict(ref, LOOKUP_ERROR, 0.0, None, {}, sources_checked=checked,
                           notes=["Every source errored (network/rate limit). Verify manually."])
        if ref.is_grey_literature:
            return Verdict(ref, UNVERIFIABLE, 0.0, None, {}, sources_checked=checked,
                           notes=[f"'{ref.entry_type}' items are often not indexed in "
                                  "Crossref/OpenAlex/PubMed; could not confirm automatically."])
        return Verdict(ref, NOT_FOUND, 0.0, None, {}, sources_checked=checked,
                       notes=["No matching record in Crossref, OpenAlex, or PubMed. "
                              "Possible fabrication, typo, or non-indexed source — verify manually."])

    scores = match.score_reference(ref, record)
    conf = match.overall_confidence(scores)
    title_s = scores.get("title")
    resolved_by_id = ref.has_identifier

    # Retraction. Authoritative when the record came from an exact identifier
    # lookup. On the query path it is only trustworthy if the candidate is a
    # strong enough match to actually BE the cited work — otherwise a weak fuzzy
    # hit to some unrelated retracted paper would be mislabeled RETRACTED.
    if record.is_retracted:
        by = ", ".join(record.retraction_sources or ["source"])
        good_query_match = title_s is not None and title_s >= T_QUERY_LIKELY_TITLE
        if resolved_by_id or good_query_match:
            notes.append(f"Flagged RETRACTED by: {by}.")
            ret_conf = max(conf, 0.85) if resolved_by_id else conf
            return Verdict(ref, RETRACTED, ret_conf, record, scores, notes, checked)
        # Weak match to a retracted work: note it, but do NOT assert retraction —
        # fall through to the normal (low-confidence) query classification below.
        notes.append(f"The closest indexed record appears retracted ({by}), but it is a "
                     "weak match — confirm whether it is the work you cited.")

    # Enrichment (only for records we keep, and only when a real contact email is
    # configured): an open-access link + a DOAJ open-access-journal listing. DOAJ
    # is a POSITIVE signal only — its absence is never evidence of a bad venue.
    if cfg.check_open_access:
        if record.doi:
            if not record.oa_url:
                record.oa_url = clients.unpaywall_oa(record.doi)
            checked.append("unpaywall")
        if record.issn:
            record.doaj_listed = clients.doaj_journal_listed(record.issn, record.container)
            checked.append("doaj")
            if record.doaj_listed:
                notes.append("Venue is listed in DOAJ (open-access journal).")

    if resolved_by_id:
        # The identifier is real; does it point at the cited work?
        if title_s is None:
            notes.append("Identifier resolves; no title supplied to cross-check.")
            return Verdict(ref, VERIFIED, 0.9, record, scores, notes, checked)
        if title_s >= T_IDENTIFIER_TITLE_OK:
            return Verdict(ref, VERIFIED, max(conf, 0.85), record, scores, notes, checked)
        notes.append(f"Identifier resolves, but to a different title "
                     f"(title similarity {title_s:.2f}). The DOI/PMID may be wrong or reused.")
        return Verdict(ref, MISMATCH, conf, record, scores, notes, checked)

    # Resolved only by query — require multi-field agreement before trusting.
    strong_second = (scores.get("year") == 1.0) or ((scores.get("author") or 0) >= 0.7)
    if title_s is not None and title_s >= T_QUERY_VERIFIED_TITLE and strong_second:
        return Verdict(ref, VERIFIED, max(conf, 0.85), record, scores, notes, checked)
    if title_s is not None and title_s >= T_QUERY_LIKELY_TITLE:
        notes.append("Closest indexed record shown; confirm it is the intended work.")
        return Verdict(ref, LIKELY_MATCH, conf, record, scores, notes, checked)

    # No confident match. If a source errored, we cannot claim "not found" — the
    # true match may live in the source that failed (partial-failure guard).
    if clients.notes:
        notes.append("A source errored during lookup; result may be incomplete — verify manually.")
        return Verdict(ref, LOOKUP_ERROR, conf, record, scores, notes, checked)
    if ref.is_grey_literature:
        notes.append("No confident match; grey literature is often not indexed.")
        return Verdict(ref, UNVERIFIABLE, conf, record, scores, notes, checked)
    notes.append("No confident match to any indexed record — verify manually.")
    return Verdict(ref, NOT_FOUND, conf, record, scores, notes, checked)


def verify_bibliography(references: list[Reference], cfg: VerifyConfig) -> VerificationReport:
    truncated_from = None
    if len(references) > cfg.max_references:
        truncated_from = len(references)
        references = references[: cfg.max_references]

    clients = BiblioClients(cfg.client)

    def _run(ref: Reference) -> Verdict:
        # Each thread gets its own client so requests.Session use stays safe and
        # per-reference transport errors don't cross-contaminate other verdicts.
        local = BiblioClients(cfg.client)
        return verify_one(ref, local, cfg)

    workers = max(1, min(cfg.max_workers, len(references)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        verdicts = list(pool.map(_run, references))

    report = VerificationReport(verdicts=verdicts, truncated_from=truncated_from)
    report.meta = {
        "sources": ["crossref", "openalex", "pubmed", "arxiv"],
        "enrichment_sources": (["unpaywall", "doaj"] if cfg.check_open_access else []),
        "contact_email": cfg.client.contact_email,
        "open_access_checked": cfg.check_open_access,
        "thresholds": {
            "identifier_title_ok": T_IDENTIFIER_TITLE_OK,
            "query_verified_title": T_QUERY_VERIFIED_TITLE,
            "query_likely_title": T_QUERY_LIKELY_TITLE,
        },
    }
    return report
