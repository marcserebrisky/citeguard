"""CiteGuard A2A adapter (Path B).

Thin glue between the A2A framework and the ``citeguard`` engine. All real work
lives in the ``citeguard`` package; this file only maps the incoming request to
``verify_bibliography`` and returns the dual-channel result.

Run locally:
    python -m agent_skeleton.serve serve-handler \\
        --file handler.py --class CiteGuardHandler --port 9110
"""
from __future__ import annotations

import asyncio

from agent_skeleton import AgentHandler, FileInput

from citeguard import (
    build_config, build_result, looks_like_references, parse_references,
    verify_bibliography,
)

_EMPTY_HELP = (
    "No references found to check.\n\n"
    "Attach a `.bib`, `.ris`, or `.docx` file, or paste a reference list, and "
    "CiteGuard will verify each citation against Crossref, OpenAlex, and PubMed — "
    "flagging anything retracted, not found (possibly fabricated), or whose "
    "metadata doesn't match the record.\n\n"
    "Only identifiers, titles, authors, and years are sent to those public APIs; "
    "your manuscript body is never transmitted."
)


class CiteGuardHandler(AgentHandler):
    """Verifies a bibliography: retractions, fabrications, and metadata mismatches."""

    async def handle_structured(self, user_input="", files=None, context=None) -> dict:
        files = files or []
        cfg = build_config(self.config, context)

        references = []
        for f in files:
            references.extend(_parse_file(f))

        # Treat pasted text as references only when it actually looks like a
        # citation list — otherwise it's an instruction accompanying a file.
        text = (user_input or "").strip()
        if text and (not files or looks_like_references(text)):
            try:  # malformed pasted BibTeX/RIS must not crash the run (as with files)
                parsed = parse_references(text=text)
            except Exception:
                parsed = []
            # Drop a lone instruction ("check my refs") that isn't a real citation.
            if parsed and not (len(parsed) > 1 or looks_like_references(text) or parsed[0].has_identifier):
                parsed = []
            references.extend(parsed)

        if not references:
            return {
                "answer": _EMPTY_HELP,
                "summary": {"TOTAL": 0},
                "references": [],
                "meta": {"note": "no parseable references in input"},
            }

        # Verification is blocking (network I/O in a thread pool); run it off the
        # event loop so the framework heartbeat keeps the A2A connection alive.
        report = await asyncio.to_thread(verify_bibliography, references, cfg)
        return build_result(report)


def _parse_file(f: FileInput) -> list:
    try:
        return parse_references(file_bytes=f.bytes, filename=f.name, mime=f.mime_type)
    except Exception as exc:  # a malformed upload must not crash the whole run
        return _wrap_parse_error(f, exc)


def _wrap_parse_error(f: FileInput, exc: Exception) -> list:
    from citeguard import Reference
    name = f.name or "attachment"
    return [Reference(
        raw=f"[could not parse {name}: {type(exc).__name__}]",
        key=name,
        entry_type="misc",
        source_format="error",
    )]
