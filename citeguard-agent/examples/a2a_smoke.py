"""Send a real A2A request to a locally-served CiteGuard and print the response.

    # terminal 1:
    python -m agent_skeleton.serve serve-handler \\
        --file handler.py --class CiteGuardHandler --port 9110
    # terminal 2:
    python examples/a2a_smoke.py

Proves the deployed path end-to-end: the .bib is base64-encoded into an A2A
FilePart, decoded by the framework, and the dual-channel result (DataPart
artifact + human text) comes back.
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from pathlib import Path

import requests

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9110/"
bib = (Path(__file__).resolve().parents[1] / "tests" / "sample.bib").read_bytes()

request = {
    "jsonrpc": "2.0",
    "id": "smoke-1",
    "method": "message/send",
    "params": {
        "message": {
            "role": "user",
            "kind": "message",
            "messageId": uuid.uuid4().hex,
            "parts": [
                {"kind": "text", "text": "Verify the references in this file."},
                {"kind": "file", "file": {
                    "name": "sample.bib",
                    "mimeType": "text/x-bibtex",
                    "bytes": base64.b64encode(bib).decode("ascii"),
                }},
            ],
        }
    },
}

resp = requests.post(URL, json=request, timeout=180)
print("HTTP", resp.status_code)
data = resp.json()

if "error" in data:
    print("JSON-RPC error:", json.dumps(data["error"], indent=2))
    sys.exit(1)

result = data.get("result", {})

# Pull the structured DataPart out of the task artifacts.
structured = None
for artifact in result.get("artifacts", []) or []:
    for part in artifact.get("parts", []) or []:
        root = part.get("data") if isinstance(part, dict) else None
        if root is not None:
            structured = root
            break

# Pull the human-readable final text.
status_msg = (result.get("status") or {}).get("message") or {}
text_parts = [p.get("text") for p in status_msg.get("parts", []) or [] if p.get("text")]

print("\n=== task state:", (result.get("status") or {}).get("state"))
print("\n=== human answer (first 800 chars) ===")
print(("\n".join(text_parts))[:800])
print("\n=== structured summary ===")
if structured:
    print(json.dumps(structured.get("summary", structured), indent=2))
else:
    print("(no structured DataPart found — full result below)")
    print(json.dumps(result, indent=2)[:1500])
