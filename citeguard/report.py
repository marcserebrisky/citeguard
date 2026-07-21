"""Render a VerificationReport as (a) human-readable markdown and (b) a
structured dict the planner / another agent can reuse.

The returned dict always has an ``answer`` key (required by AgentHandler).
"""
from __future__ import annotations

from typing import Any

from .models import (
    LIKELY_MATCH, LOOKUP_ERROR, MISMATCH, NOT_FOUND, RETRACTED, UNVERIFIABLE,
    VERIFIED, VerificationReport, Verdict,
)

_ICON = {
    RETRACTED: "⛔",
    NOT_FOUND: "❌",
    MISMATCH: "⚠️",
    LIKELY_MATCH: "🔎",
    UNVERIFIABLE: "❓",
    LOOKUP_ERROR: "🔌",
    VERIFIED: "✅",
}
_LABEL = {
    RETRACTED: "RETRACTED",
    NOT_FOUND: "NOT FOUND",
    MISMATCH: "METADATA MISMATCH",
    LIKELY_MATCH: "LIKELY MATCH (confirm)",
    UNVERIFIABLE: "UNVERIFIABLE (grey literature)",
    LOOKUP_ERROR: "LOOKUP ERROR",
    VERIFIED: "VERIFIED",
}
# Order sections so the actionable problems come first.
_SECTION_ORDER = [RETRACTED, NOT_FOUND, MISMATCH, LIKELY_MATCH, UNVERIFIABLE, LOOKUP_ERROR, VERIFIED]

_DISCLOSURE = (
    "Only identifiers, titles, author names, and years are sent to the public "
    "APIs (Crossref, OpenAlex, PubMed, DOAJ, Unpaywall). Your manuscript body is "
    "never transmitted."
)
_LIMITS = (
    "CiteGuard confirms that a citation resolves to a real, non-retracted record "
    "and that the metadata agrees. It does not judge whether a source is "
    "appropriate or correctly interpreted. Books, theses, and reports are often "
    "not indexed and are marked UNVERIFIABLE, not wrong. Absence from DOAJ is not "
    "evidence a journal is predatory. Always confirm flagged items against the "
    "linked record before acting."
)


def _verdict_line(v: Verdict) -> str:
    rec = v.record
    head = f"- {_ICON.get(v.status, '•')} **{_LABEL.get(v.status, v.status)}**: {v.reference.label}"
    detail: list[str] = []
    if rec and rec.url:
        detail.append(f"[{rec.source} record]({rec.url})")
    if rec and rec.doi:
        detail.append(f"DOI `{rec.doi}`")
    if v.scores:
        detail.append("match " + ", ".join(f"{k} {int(round(val * 100))}%" for k, val in v.scores.items()))
    if rec and rec.oa_url:
        detail.append(f"[open access]({rec.oa_url})")
    if rec and rec.doaj_listed:
        detail.append("DOAJ-listed OA journal")
    line = head
    if detail:
        line += "\n    " + " · ".join(detail)
    for note in v.notes:
        line += f"\n    _{note}_"
    return line


def render_markdown(report: VerificationReport) -> str:
    c = report.counts
    total = c["TOTAL"]
    if total == 0:
        return ("No references were found to check. Attach a `.bib`, `.ris`, or "
                "`.docx` file, or paste a reference list.")

    problems = c[RETRACTED] + c[NOT_FOUND] + c[MISMATCH]
    lines: list[str] = []
    lines.append(f"## CiteGuard: checked {total} reference{'s' if total != 1 else ''}")
    headline = (f"**{problems} need attention** "
                f"({c[RETRACTED]} retracted, {c[NOT_FOUND]} not found, {c[MISMATCH]} mismatched)."
                if problems else "**No retracted, missing, or mismatched citations found.**")
    lines.append(headline)
    summary_bits = [f"{_ICON[s]} {_LABEL[s].split(' (')[0]}: {c[s]}"
                    for s in _SECTION_ORDER if c[s]]
    lines.append(" | ".join(summary_bits))
    if report.truncated_from:
        lines.append(f"> ⚠️ Only the first {total} of {report.truncated_from} references were "
                     "checked (per-request cap).")

    by_status: dict[str, list[Verdict]] = {}
    for v in report.verdicts:
        by_status.setdefault(v.status, []).append(v)

    for status in _SECTION_ORDER:
        group = by_status.get(status)
        if not group:
            continue
        lines.append(f"\n### {_ICON[status]} {_LABEL[status]} ({len(group)})")
        lines.extend(_verdict_line(v) for v in group)

    lines.append("\n---")
    lines.append(f"**Data handling:** {_DISCLOSURE}")
    lines.append(f"**Limitations:** {_LIMITS}")
    return "\n".join(lines)


def build_result(report: VerificationReport) -> dict[str, Any]:
    """The dual-channel payload: human ``answer`` + structured data."""
    return {
        "answer": render_markdown(report),
        "summary": report.counts,
        "references": [v.to_dict() for v in report.verdicts],
        "meta": {
            **report.meta,
            "truncated_from": report.truncated_from,
            "data_flow_disclosure": _DISCLOSURE,
            "limitations": _LIMITS,
        },
    }
