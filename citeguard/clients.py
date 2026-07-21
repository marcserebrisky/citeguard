"""Thin clients for the authoritative bibliographic APIs CiteGuard trusts.

All keyless (an NCBI key only raises PubMed's rate limit). Every method returns
a normalised ``FoundRecord`` or ``None`` — never raises to the caller — and
records a short note on failure so the verifier can report "could not check X"
instead of guessing. No manuscript text is ever sent: only identifiers, titles,
author names, and years leave the machine.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import requests

from .models import FoundRecord

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DOAJ = "https://doaj.org/api/search/journals"
UNPAYWALL = "https://api.unpaywall.org/v2"
ARXIV = "http://export.arxiv.org/api/query"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}

_RETRACTED_TITLE_RE = ("retracted:", "retraction:", "[retracted", "withdrawn:")


def _host(url: str) -> str:
    return url.split("//")[-1].split("/")[0]


def _retry_after_seconds(resp: requests.Response) -> float | None:
    """Retry-After as seconds, or None for the RFC-7231 HTTP-date form (which
    we don't parse — the caller falls back to exponential backoff)."""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class ClientConfig:
    contact_email: str = "citeguard@example.org"
    ncbi_api_key: str | None = None
    timeout: float = 20.0
    max_retries: int = 3
    user_agent: str = "CiteGuard/0.1"


class BiblioClients:
    def __init__(self, config: ClientConfig | None = None):
        self.cfg = config or ClientConfig()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"{self.cfg.user_agent} (mailto:{self.cfg.contact_email})",
            "Accept": "application/json",
        })
        self.notes: list[str] = []

    # -- low-level GET with polite retry/backoff ----------------------------
    def _request(self, url: str, params: dict[str, Any] | None) -> requests.Response | None:
        last_error: str | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.cfg.timeout)
            except requests.RequestException as exc:
                last_error = type(exc).__name__
                time.sleep(0.5 * (2 ** attempt))
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
                wait = _retry_after_seconds(resp) or (0.5 * (2 ** attempt))
                time.sleep(min(wait, 8.0))
                continue
            if resp.status_code >= 400:  # other 4xx: not transient — record & stop.
                self.notes.append(f"request to {_host(url)} failed: HTTP {resp.status_code}")
                return None
            return resp
        # Retries exhausted on a transport error or 429/5xx. Record it so the
        # verifier reports LOOKUP_ERROR rather than a false "not found".
        if last_error is not None:
            self.notes.append(
                f"request to {_host(url)} failed after {self.cfg.max_retries} tries: {last_error}")
        return None

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        resp = self._request(url, params)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            self.notes.append(f"non-JSON response from {_host(url)}")
            return None

    def _get_text(self, url: str, params: dict[str, Any] | None = None) -> str | None:
        resp = self._request(url, params)
        return resp.text if resp is not None else None

    # -- Crossref -----------------------------------------------------------
    def crossref_by_doi(self, doi: str) -> FoundRecord | None:
        data = self._get(f"{CROSSREF}/{doi}", {"mailto": self.cfg.contact_email})
        if not data or "message" not in data:
            return None
        return _crossref_record(data["message"])

    def crossref_by_query(self, *, bibliographic: str, author: str | None = None,
                          rows: int = 5) -> list[FoundRecord]:
        # NOTE: `subtype`/`update-to` are NOT valid `select` fields on the /works
        # list route (they 400 the request); retraction on query hits is confirmed
        # via the title marker + an OpenAlex cross-check in verify._resolve.
        params = {"query.bibliographic": bibliographic[:600], "rows": rows,
                  "mailto": self.cfg.contact_email,
                  "select": "DOI,title,author,issued,container-title,relation,type"}
        if author:
            params["query.author"] = author[:200]
        data = self._get(CROSSREF, params)
        if not data:
            return []
        items = (data.get("message") or {}).get("items") or []
        return [_crossref_record(it) for it in items]

    # -- OpenAlex -----------------------------------------------------------
    def openalex_by_doi(self, doi: str) -> FoundRecord | None:
        return self._openalex(f"{OPENALEX}/doi:{doi}")

    def openalex_by_pmid(self, pmid: str) -> FoundRecord | None:
        return self._openalex(f"{OPENALEX}/pmid:{pmid}")

    def _openalex(self, url: str) -> FoundRecord | None:
        data = self._get(url, {"mailto": self.cfg.contact_email})
        if not data or data.get("id") is None:
            return None
        return _openalex_record(data)

    def openalex_search(self, title: str) -> FoundRecord | None:
        """Best title match — recall for preprints/works Crossref may miss."""
        if not title:
            return None
        data = self._get(OPENALEX, {"search": title[:350], "per_page": 1,
                                    "mailto": self.cfg.contact_email})
        results = (data or {}).get("results") or []
        return _openalex_record(results[0]) if results else None

    # -- arXiv (authoritative resolver for an arXiv id) ---------------------
    def arxiv_by_id(self, arxiv_id: str) -> FoundRecord | None:
        """Resolve an arXiv id to its real record via the arXiv API (Atom XML).

        The id uniquely identifies the preprint, so this is authoritative — no
        fuzzy title matching. Returns None if the id does not exist (arXiv
        returns an error entry whose <id> lacks '/abs/')."""
        text = self._get_text(ARXIV, {"id_list": arxiv_id, "max_results": 1})
        if not text:
            return None
        try:
            entry = ET.fromstring(text).find("a:entry", _ATOM)
        except ET.ParseError:
            return None
        if entry is None:
            return None
        eid = (entry.findtext("a:id", default="", namespaces=_ATOM) or "")
        if "/abs/" not in eid:
            return None  # arXiv's error entry for a nonexistent id
        title = " ".join((entry.findtext("a:title", default="", namespaces=_ATOM) or "").split())
        authors = [(a.findtext("a:name", default="", namespaces=_ATOM) or "").strip()
                   for a in entry.findall("a:author", _ATOM)]
        published = entry.findtext("a:published", default="", namespaces=_ATOM) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        return FoundRecord(
            source="arxiv",
            title=title or None,
            authors=[a for a in authors if a],
            year=year,
            container="arXiv",
            url=eid.replace("http://", "https://"),
        )

    # -- PubMed (E-utilities) ----------------------------------------------
    def pubmed_by_pmid(self, pmid: str) -> FoundRecord | None:
        params = {"db": "pubmed", "id": pmid, "retmode": "json",
                  "tool": "citeguard", "email": self.cfg.contact_email}
        if self.cfg.ncbi_api_key:
            params["api_key"] = self.cfg.ncbi_api_key
        data = self._get(f"{EUTILS}/esummary.fcgi", params)
        try:
            res = data["result"][str(pmid)]
        except (TypeError, KeyError):
            return None
        if "error" in res:
            return None
        return _pubmed_record(res, pmid)

    # -- DOAJ (open-access journal listing — a positive signal only) --------
    def doaj_journal_listed(self, issn: str | None, journal: str | None) -> bool | None:
        query = None
        if issn:
            query = f"issn:{issn}"
        elif journal:
            query = f'bibjson.title:"{journal}"'
        if not query:
            return None
        data = self._get(f"{DOAJ}/{query}", {"pageSize": 1})
        if data is None:
            return None
        return int(data.get("total", 0)) > 0

    # -- Unpaywall (open-access link) ---------------------------------------
    def unpaywall_oa(self, doi: str) -> str | None:
        data = self._get(f"{UNPAYWALL}/{doi}", {"email": self.cfg.contact_email})
        if not data:
            return None
        loc = data.get("best_oa_location") or {}
        return loc.get("url_for_pdf") or loc.get("url")


# --- normalisers ------------------------------------------------------------

def _year_from_parts(parts: Any) -> int | None:
    try:
        return int(parts["date-parts"][0][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _crossref_record(msg: dict) -> FoundRecord:
    title = (msg.get("title") or [None])[0]
    authors = [f"{a.get('given', '')} {a.get('family', '')}".strip()
               for a in (msg.get("author") or [])]
    retracted, sources = _crossref_retraction(msg, title)
    doi = (msg.get("DOI") or "").lower() or None
    return FoundRecord(
        source="crossref",
        title=title,
        authors=[a for a in authors if a],
        year=_year_from_parts(msg.get("issued") or {}),
        container=(msg.get("container-title") or [None])[0],
        issn=(msg.get("ISSN") or [None])[0],
        doi=doi,
        url=f"https://doi.org/{doi}" if doi else None,
        is_retracted=retracted,
        retraction_sources=sources,
        raw={"type": msg.get("type")},
    )


def _crossref_retraction(msg: dict, title: str | None) -> tuple[bool, list[str]]:
    sources: list[str] = []
    if title and title.strip().lower().startswith(_RETRACTED_TITLE_RE):
        sources.append("crossref:title-marker")
    for upd in msg.get("update-to") or []:
        if "retract" in (upd.get("type") or "").lower():
            sources.append("crossref:update-to")
            break
    rel = msg.get("relation") or {}
    if any("retract" in k.lower() for k in rel.keys()):
        sources.append("crossref:relation")
    return (bool(sources), sources)


def _openalex_record(work: dict) -> FoundRecord:
    doi = (work.get("doi") or "").replace("https://doi.org/", "").lower() or None
    authors = [(a.get("author") or {}).get("display_name")
               for a in (work.get("authorships") or [])]
    loc = work.get("best_oa_location") or {}
    sources = ["openalex:is_retracted"] if work.get("is_retracted") else []
    src = (work.get("primary_location") or {}).get("source") or {}
    return FoundRecord(
        source="openalex",
        title=work.get("title") or work.get("display_name"),
        authors=[a for a in authors if a],
        year=work.get("publication_year"),
        container=src.get("display_name"),
        issn=src.get("issn_l") or (src.get("issn") or [None])[0],
        doi=doi,
        url=work.get("id"),
        is_retracted=bool(work.get("is_retracted")),
        retraction_sources=sources,
        oa_url=loc.get("pdf_url") or loc.get("landing_page_url"),
        raw={"is_paratext": work.get("is_paratext")},
    )


def _pubmed_record(res: dict, pmid: str) -> FoundRecord:
    pubtypes = res.get("pubtype") or []
    retracted = any("retract" in (pt or "").lower() for pt in pubtypes)
    authors = [a.get("name") for a in (res.get("authors") or []) if a.get("name")]
    year = None
    pubdate = res.get("pubdate") or res.get("sortpubdate") or ""
    import re as _re
    m = _re.search(r"(1[5-9]\d{2}|20\d{2})", pubdate)
    if m:
        year = int(m.group(1))
    doi = None
    for aid in res.get("articleids") or []:
        if aid.get("idtype") == "doi":
            doi = (aid.get("value") or "").lower() or None
    return FoundRecord(
        source="pubmed",
        title=(res.get("title") or "").rstrip("."),
        authors=authors,
        year=year,
        container=res.get("fulljournalname") or res.get("source"),
        doi=doi,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        is_retracted=retracted,
        retraction_sources=["pubmed:pubtype"] if retracted else [],
        raw={"pubtype": pubtypes},
    )
