"""Run CiteGuard end-to-end against the live APIs — no server needed.

    python examples/run_local.py [path/to/refs.bib]

Defaults to tests/sample.bib. Calls the real handler exactly as the A2A wrapper
would, so a green run here means the deployed agent will behave the same.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citeguard import build_config, build_result, parse_references, verify_bibliography


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("sample.bib")
    if not path.exists():
        path = Path(__file__).resolve().parents[1] / "tests" / "sample.bib"
    refs = parse_references(file_bytes=path.read_bytes(), filename=path.name)
    print(f"Parsed {len(refs)} references from {path.name}\n")

    cfg = build_config(config={}, context=None)
    report = verify_bibliography(refs, cfg)
    result = build_result(report)

    print(result["answer"])
    print("\n=== structured summary ===")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
