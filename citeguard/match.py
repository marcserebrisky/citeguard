"""Per-field similarity scoring between a user Reference and a FoundRecord.

Kept deliberately conservative: a "verified" verdict requires *multiple* fields
to agree, so a fuzzy title match alone can never bind a fabricated citation to a
real-but-different record.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .models import FoundRecord, Reference

# Weights over the fields that are actually present (renormalised by availability).
_WEIGHTS = {"title": 0.60, "author": 0.25, "year": 0.15}


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def _last_name(name: str) -> str:
    name = name.strip()
    if "," in name:
        return _norm(name.split(",")[0])
    parts = _norm(name).split()
    return parts[-1] if parts else ""


def title_score(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return fuzz.token_sort_ratio(_norm(a), _norm(b)) / 100.0


def author_score(ref_authors: list[str], rec_authors: list[str]) -> float | None:
    if not ref_authors or not rec_authors:
        return None
    ref_last = {_last_name(a) for a in ref_authors if _last_name(a)}
    rec_last = {_last_name(a) for a in rec_authors if _last_name(a)}
    if not ref_last or not rec_last:
        return None
    # Reward first-author agreement strongly, plus overall surname overlap.
    first_match = 1.0 if _last_name(ref_authors[0]) in rec_last else 0.0
    overlap = len(ref_last & rec_last) / len(ref_last)
    return round(0.5 * first_match + 0.5 * overlap, 3)


def year_score(a: int | None, b: int | None) -> float | None:
    if not a or not b:
        return None
    if a == b:
        return 1.0
    if abs(a - b) == 1:  # off-by-one: online-first vs issue year
        return 0.5
    return 0.0


def score_reference(ref: Reference, record: FoundRecord) -> dict[str, float]:
    scores: dict[str, float] = {}
    t = title_score(ref.title, record.title)
    if t is not None:
        scores["title"] = round(t, 3)
    a = author_score(ref.authors, record.authors)
    if a is not None:
        scores["author"] = a
    y = year_score(ref.year, record.year)
    if y is not None:
        scores["year"] = y
    return scores


def overall_confidence(scores: dict[str, float]) -> float:
    present = {k: v for k, v in scores.items() if k in _WEIGHTS}
    if not present:
        return 0.0
    total_w = sum(_WEIGHTS[k] for k in present)
    return round(sum(_WEIGHTS[k] * v for k, v in present.items()) / total_w, 3)
