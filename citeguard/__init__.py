"""CiteGuard — verify a reference list against authoritative bibliographic APIs.

Public API:
    parse_references(...)        -> list[Reference]
    looks_like_references(text)  -> bool
    verify_bibliography(refs, cfg) -> VerificationReport
    build_result(report)         -> dict  (has an "answer" key)
    build_config(config, context)-> VerifyConfig

The engine imports nothing from ``agent_skeleton`` — it can be unit-tested and
run standalone. The A2A adapter lives in ``handler.py`` at the repo root.
"""
from __future__ import annotations

import os
from typing import Any

from .clients import ClientConfig
from .models import (  # noqa: F401  (re-exported for consumers)
    LIKELY_MATCH, LOOKUP_ERROR, MISMATCH, NOT_FOUND, RETRACTED, UNVERIFIABLE,
    VERIFIED, FoundRecord, Reference, Verdict, VerificationReport,
)
from .parse import looks_like_references, parse_references
from .report import build_result, render_markdown
from .verify import VerifyConfig, verify_bibliography, verify_one

__all__ = [
    "parse_references", "looks_like_references", "verify_bibliography",
    "verify_one", "build_result", "render_markdown", "build_config",
    "VerifyConfig", "ClientConfig", "Reference", "Verdict",
    "FoundRecord", "VerificationReport",
]

_PLACEHOLDER_EMAIL = "citeguard@example.org"


def build_config(config: dict[str, Any] | None = None,
                 context: dict[str, Any] | None = None) -> VerifyConfig:
    """Assemble a VerifyConfig from (non-secret) handler config, per-user
    credentials, and environment — in that order of precedence for the email,
    and credentials-first for the optional NCBI key. Never logs secrets."""
    config = config or {}
    creds = (context or {}).get("credentials", {}) or {}

    contact_email = (
        config.get("contact_email")
        or os.getenv("CITEGUARD_CONTACT_EMAIL")
        or _PLACEHOLDER_EMAIL
    )
    ncbi_api_key = (
        (creds.get("ncbi_api_key") or {}).get("api_key")
        or os.getenv("NCBI_API_KEY")
    )
    # Open-access (Unpaywall) lookups are only polite with a real contact email.
    check_oa = bool(config.get("check_open_access", contact_email != _PLACEHOLDER_EMAIL))

    return VerifyConfig(
        client=ClientConfig(contact_email=contact_email, ncbi_api_key=ncbi_api_key),
        check_open_access=check_oa,
        max_workers=int(config.get("max_workers", 8)),
    )


def has_real_contact_email(cfg: VerifyConfig) -> bool:
    return cfg.client.contact_email != _PLACEHOLDER_EMAIL
