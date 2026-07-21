"""Turn raw user input (.bib / .ris / .docx / pasted text) into ``Reference``s.

Deterministic, no LLM. Structured formats (.bib/.ris) give clean fields; free
text is best-effort — we always keep the original string in ``Reference.raw`` so
the verifier can fall back to a Crossref bibliographic query when no identifier
is present.
"""
from __future__ import annotations

import io
import re
from typing import Iterable

from .models import Reference

# --- Identifier regexes -----------------------------------------------------
# DOI: the canonical Crossref pattern, then we trim trailing punctuation that
# commonly clings to a DOI at the end of a sentence.
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
_DOI_TRAILING = ".,;)]}>\"'"
_ARXIV_RE = re.compile(r"arXiv:\s*([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", re.IGNORECASE)
_ARXIV_OLD_RE = re.compile(r"arXiv:\s*([a-z\-]+(?:\.[A-Z]{2})?/[0-9]{7}(?:v[0-9]+)?)", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID:?\s*([0-9]{1,9})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(1[5-9][0-9]{2}|20[0-9]{2})\b")
# A numbered-list marker at the start of a reference line: "1." "[1]" "(1)" "1)"
_LIST_MARKER_RE = re.compile(r"^\s*(?:\[\d+\]|\(\d+\)|\d+[.)])\s+")
# A bibliography section heading, tolerant of numbering, extra words, and a
# trailing ':' or '.': "References", "References:", "REFERENCE LIST",
# "Notes and References", "Selected Bibliography", "7. Literature Cited".
_HEADING_RE = re.compile(
    r"\s*(?:\d+[.)]?\s*)?(?:[\w ]{0,24}\b)?"
    r"(references?(?: list)?|bibliography|works cited|literature cited)\s*[:.]?\s*",
    re.IGNORECASE,
)


def _decode_text(data: bytes) -> str:
    """Decode uploaded bytes, tolerating UTF-8, UTF-16 (BOM), and legacy encodings.

    UTF-16 exports (EndNote / Windows Notepad "Unicode") start with a BOM that
    utf-8-sig can't strip; without this a valid .ris/.bib would decode to
    NUL-interleaved mojibake and silently parse to zero references.
    """
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("latin-1", errors="replace")


def clean_doi(raw: str | None) -> str | None:
    """Normalise a DOI: strip a URL prefix, trailing punctuation, lowercase."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^doi:\s*", "", s, flags=re.IGNORECASE)
    m = _DOI_RE.search(s)
    if not m:
        return None
    doi = m.group(0)
    while doi and doi[-1] in _DOI_TRAILING:
        doi = doi[:-1]
    return doi.lower()


def _extract_identifiers(text: str, ref: Reference) -> None:
    if ref.doi is None:
        ref.doi = clean_doi(text)
    if ref.arxiv_id is None:
        m = _ARXIV_RE.search(text) or _ARXIV_OLD_RE.search(text)
        if m:
            ref.arxiv_id = m.group(1)
    if ref.pmid is None:
        m = _PMID_RE.search(text)
        if m:
            ref.pmid = m.group(1)
    if ref.year is None:
        m = _YEAR_RE.search(text)
        if m:
            ref.year = int(m.group(1))


# --- BibTeX -----------------------------------------------------------------

def parse_bibtex(text: str) -> list[Reference]:
    import bibtexparser
    from bibtexparser.bparser import BibTexParser

    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    db = bibtexparser.loads(text, parser=parser)
    refs: list[Reference] = []
    for e in db.entries:
        authors = _split_bib_authors(e.get("author", ""))
        year = None
        if e.get("year"):
            m = _YEAR_RE.search(e["year"])
            year = int(m.group(1)) if m else None
        ref = Reference(
            raw=_bib_entry_to_raw(e),
            key=e.get("ID"),
            entry_type=(e.get("ENTRYTYPE") or "").lower() or None,
            doi=clean_doi(e.get("doi")) or clean_doi(e.get("DOI")),
            pmid=(e.get("pmid") or e.get("PMID") or None),
            arxiv_id=_arxiv_from_bib(e),
            title=_strip_braces(e.get("title")),
            authors=authors,
            year=year,
            journal=_strip_braces(e.get("journal") or e.get("booktitle") or e.get("publisher")),
            source_format="bib",
        )
        # Backfill identifiers from the fields where they actually hide (a DOI in
        # `url`, a PMID in `note`, etc.) — not the reconstructed raw, which omits them.
        extra = " ".join(str(e.get(k) or "") for k in ("note", "url", "eprint", "howpublished"))
        _extract_identifiers(f"{ref.raw} {extra}", ref)
        refs.append(ref)
    return refs


def _split_bib_authors(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"\s+and\s+", _strip_braces(raw) or "")
    return [p.strip() for p in parts if p.strip()]


def _arxiv_from_bib(entry: dict) -> str | None:
    for field_ in ("eprint", "archiveprefix", "journal", "note", "url"):
        val = entry.get(field_) or entry.get(field_.upper())
        if not val:
            continue
        m = _ARXIV_RE.search(val) or _ARXIV_OLD_RE.search(val)
        if m:
            return m.group(1)
        if field_ == "eprint" and re.fullmatch(r"[0-9]{4}\.[0-9]{4,5}(v[0-9]+)?", val.strip()):
            return val.strip()
    return None


def _strip_braces(val: str | None) -> str | None:
    if not val:
        return None
    return re.sub(r"[{}]", "", val).strip() or None


def _bib_entry_to_raw(entry: dict) -> str:
    bits = []
    if entry.get("author"):
        bits.append(_strip_braces(entry["author"]) or "")
    if entry.get("year"):
        bits.append(f"({entry['year']})")
    if entry.get("title"):
        bits.append(_strip_braces(entry["title"]) or "")
    if entry.get("journal") or entry.get("booktitle"):
        bits.append(_strip_braces(entry.get("journal") or entry.get("booktitle")) or "")
    if entry.get("doi") or entry.get("DOI"):
        bits.append(f"doi:{entry.get('doi') or entry.get('DOI')}")
    return ". ".join(b for b in bits if b)


# --- RIS --------------------------------------------------------------------

def parse_ris(text: str) -> list[Reference]:
    refs: list[Reference] = []
    cur: dict[str, list[str]] = {}

    def flush() -> None:
        if not cur:
            return
        title = (cur.get("TI") or cur.get("T1") or [None])[0]
        journal = (cur.get("JO") or cur.get("JF") or cur.get("T2") or [None])[0]
        year = None
        if cur.get("PY") or cur.get("Y1"):
            m = _YEAR_RE.search((cur.get("PY") or cur.get("Y1"))[0])
            year = int(m.group(1)) if m else None
        ref = Reference(
            raw="; ".join(f"{k}:{'/'.join(v)}" for k, v in cur.items()),
            entry_type=(cur.get("TY") or [None])[0],
            doi=clean_doi((cur.get("DO") or [None])[0]),
            title=title,
            authors=cur.get("AU") or cur.get("A1") or [],
            year=year,
            journal=journal,
            source_format="ris",
        )
        _extract_identifiers(ref.raw, ref)
        refs.append(ref)
        cur.clear()

    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s+-\s?(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "ER":
            flush()
            continue
        cur.setdefault(tag, []).append(val)
    flush()
    return refs


# --- DOCX / plain text ------------------------------------------------------

def parse_docx(data: bytes) -> list[Reference]:
    import docx  # python-docx

    doc = docx.Document(io.BytesIO(data))
    paras = [p.text.strip() for p in doc.paragraphs]
    # If there is a References/Bibliography heading, keep only what follows it.
    start = None
    for i, t in enumerate(paras):
        if t and _HEADING_RE.fullmatch(t):
            start = i + 1
            break
    if start is not None:
        body = [t for t in paras[start:] if t]
    else:
        # No recognizable heading: keep only citation-like paragraphs, so a full
        # manuscript's title/abstract/prose isn't misparsed as references.
        body = [t for t in paras if t and looks_like_references(t)]
    return _references_from_lines(body, source_format="docx")


def parse_text(text: str) -> list[Reference]:
    return _references_from_lines(_split_text_into_references(text), source_format="text")


def _split_text_into_references(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    # 1) Blank-line separated blocks.
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) > 1:
        return blocks
    # 2) Numbered-list markers: start a new reference at each marker and fold
    #    wrapped continuation lines into the current one (PDF/Word copy-paste).
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if sum(1 for ln in lines if _LIST_MARKER_RE.match(ln)) >= 2:
        grouped: list[str] = []
        for ln in lines:
            if _LIST_MARKER_RE.match(ln) or not grouped:
                grouped.append(ln.strip())
            else:
                grouped[-1] += " " + ln.strip()
        return grouped
    # 3) One reference per line (last resort).
    return [ln.strip() for ln in lines]


def _references_from_lines(lines: Iterable[str], source_format: str) -> list[Reference]:
    refs: list[Reference] = []
    for i, raw in enumerate(lines, start=1):
        raw = _LIST_MARKER_RE.sub("", raw).strip()
        if len(raw) < 8:  # skip stray fragments / page numbers
            continue
        ref = Reference(raw=raw, key=str(i), source_format=source_format)
        _extract_identifiers(raw, ref)
        ref.title = _guess_title(raw)
        ref.authors = _guess_authors(raw)
        ref.entry_type = "article"  # unknown; assume article so no-hit => NOT_FOUND
        refs.append(ref)
    return refs


def _guess_title(raw: str) -> str | None:
    """Best-effort title from a free-text citation.

    Heuristics only — the verifier does not depend on this being perfect; when no
    identifier is present it queries Crossref with the whole ``raw`` string.
    """
    # Quoted title.
    m = re.search(r"[\"“]([^\"”]{8,})[\"”]", raw)
    if m:
        return m.group(1).strip().rstrip(".")
    # Text after "(YEAR)." up to the next period — a common APA shape.
    m = re.search(r"\((?:1[5-9]\d{2}|20\d{2})\)\.?\s*(.+?)\.\s", raw)
    if m and len(m.group(1)) >= 8:
        return m.group(1).strip()
    return None


def _guess_authors(raw: str) -> list[str]:
    head = re.split(r"\((?:1[5-9]\d{2}|20\d{2})\)", raw)[0]
    if not head or len(head) > 220:
        return []
    parts = re.split(r",| and | & ", head)
    out = [p.strip() for p in parts if len(p.strip()) > 1]
    return out[:12]


# --- Dispatcher -------------------------------------------------------------

def parse_references(
    *,
    text: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    mime: str | None = None,
) -> list[Reference]:
    """Parse one source into references. Format detected from name/mime/content."""
    if file_bytes is not None:
        name = (filename or "").lower()
        if name.endswith(".docx") or (mime or "").endswith("wordprocessingml.document"):
            return parse_docx(file_bytes)
        decoded = _decode_text(file_bytes)
        if name.endswith(".bib") or "@" in decoded[:2000] and re.search(r"@\w+\s*\{", decoded):
            return parse_bibtex(decoded)
        if name.endswith(".ris") or re.search(r"^TY\s+-\s", decoded, re.MULTILINE):
            return parse_ris(decoded)
        return parse_text(decoded)

    if text is not None:
        stripped = text.strip()
        if re.search(r"@\w+\s*\{", stripped):
            return parse_bibtex(stripped)
        if re.search(r"^TY\s+-\s", stripped, re.MULTILINE):
            return parse_ris(stripped)
        return parse_text(stripped)

    return []


def looks_like_references(text: str) -> bool:
    """Cheap heuristic: does this pasted text contain citations (vs. an instruction)?"""
    if not text or len(text.strip()) < 20:
        return False
    if _DOI_RE.search(text) or _ARXIV_RE.search(text) or _PMID_RE.search(text):
        return True
    if re.search(r"@\w+\s*\{", text) or re.search(r"^TY\s+-\s", text, re.MULTILINE):
        return True
    # A year plus enough length reads like a reference (list), not an instruction.
    return bool(_YEAR_RE.search(text)) and len(text) >= 40
