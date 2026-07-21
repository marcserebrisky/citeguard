# CiteGuard

**Verify a reference list against authoritative bibliographic databases — catching retracted, fabricated, and mismatched citations before they reach a reviewer.**

CiteGuard is an [A2A](https://a2a-protocol.org/) agent built on the DTRC starter skeleton (**Path B** — a custom handler). You give it a bibliography (`.bib`, `.ris`, `.docx`, or a pasted reference list); it checks every citation against **Crossref, OpenAlex, PubMed, and arXiv** and returns a per-reference verdict, each anchored to a real record link or an explicit "not found." It **calls no LLM** — every verdict is deterministic and reproducible.

---

## The six questions (start here)

**1. What research workflow does it improve?**
The pre-submission / pre-review **reference-integrity check**. Before a manuscript, thesis chapter, grant, or systematic review goes out, someone should confirm that every citation (a) points to a real paper, (b) has metadata that matches the real record, and (c) hasn't been **retracted**. Today that's manual DOI-clicking, one reference at a time — tedious enough that it's usually skipped. It matters more now that people draft with LLMs, which invent plausible-looking but nonexistent citations. CiteGuard does the whole list in one pass.

**2. Who at WashU would benefit?**
- **Graduate students & PIs** finalizing a manuscript, dissertation, or grant reference list.
- **Peer reviewers & journal-club leads** doing a fast integrity pass on a submission.
- **Research administrators / grants managers** QA-ing citations in a proposal or report.
- **Becker Medical Library** staff supporting authors and systematic reviewers.

**3. What does it do that a general chatbot would not?**
A chatbot will *confirm a citation that does not exist* and cannot know today's retraction status. CiteGuard **anchors every verdict to a live authoritative record or an explicit "no record found"** — it never asserts a paper is real without a resolvable identifier, and it reads retraction status straight from Crossref/OpenAlex/PubMed. It also flags the subtle case a chatbot can't: a **real DOI attached to the wrong title** (a classic fabrication/copy-paste tell).

**4. What is it designed to handle well?**
- "Verify the references in my attached `.bib` / `.docx` / `.ris` file."
- "Check this reference list for retracted or fabricated citations." (paste the list)
- "Do all the DOIs in my bibliography resolve to the right papers?"
- Mixed lists of journal articles, preprints (arXiv), and grey literature (books/theses).
- **Ambiguous / failure inputs:** empty input → asks for a file or list; an unparseable upload → reported per-file, never crashes the run; a citation with no identifier → resolved by a bibliographic query or marked `NOT_FOUND`, never guessed.

**5. What tools, files, APIs does it use?**
Inputs: `.bib`, `.ris`, `.docx`, or pasted text. APIs (all **free/keyless**): **Crossref** (metadata + Retraction-Watch-integrated retraction signals), **OpenAlex** (`is_retracted`, cross-checks, title-search recall), **PubMed E-utilities** (biomedical retraction via publication type), **arXiv API** (authoritative resolution of arXiv IDs), plus enrichment via **DOAJ** (open-access journal listing) and **Unpaywall** (open-access links). Fuzzy matching via `rapidfuzz`. No other agents required.

**6. How does it handle uncertainty, privacy, credentials, limitations?**
- **Uncertainty:** every verdict that resolves to a record carries per-field match scores (title/author/year) and the canonical record link so a human can confirm; a miss says plainly that nothing was found. Weak matches are labeled `LIKELY_MATCH`, not `VERIFIED`.
- **No overclaiming:** a "VERIFIED" verdict requires **multi-field agreement**, so a fuzzy title match alone can never bind a fabricated citation to a real record. Retraction is asserted only from authoritative fields (OpenAlex `is_retracted`, PubMed publication type, Crossref's retraction markers), and the response names which sources flagged it.
- **Privacy:** only **identifiers, titles, author names, and years** are sent to the public APIs. **Your manuscript body is never transmitted.** This is stated in every response.
- **Credentials:** none required. An optional NCBI API key (raises PubMed rate limits) is read from `context["credentials"]` (deployed) or the `NCBI_API_KEY` env var (local) — never hard-coded.
- **Limitations (stated in output):** it confirms a citation is *real and non-retracted with matching metadata* — it does **not** judge whether a source is appropriate or correctly interpreted. Books/theses/reports are often not indexed and are marked `UNVERIFIABLE` (not "wrong"). Absence from DOAJ is **not** evidence a journal is predatory.

---

## Input / output

**Input** — any one or more of:
- an attached `.bib`, `.ris`, or `.docx` file, and/or
- a pasted reference list in the message text.

**Output** — the standard dual-channel A2A response:
- **`answer`** (human-readable markdown): a summary line, then references grouped by verdict (problems first), each with the record link, match scores, and notes; plus a data-handling + limitations footer.
- **structured keys** (machine-readable `DataPart`) for another agent/tool to reuse:
  - `summary` — counts per status (`{RETRACTED, NOT_FOUND, MISMATCH, LIKELY_MATCH, UNVERIFIABLE, LOOKUP_ERROR, VERIFIED, TOTAL}`).
  - `references` — one object per citation: `status`, `confidence`, `input`, `matched_record` (source, DOI, URL, `is_retracted`, `retraction_sources`, OA URL), `match_scores`, `sources_checked`, `notes`.
  - `meta` — sources consulted, thresholds used, and the data-flow disclosure.

### Verdicts

| Status | Meaning |
|---|---|
| ✅ `VERIFIED` | Resolves to a real record and the metadata agrees. |
| ⛔ `RETRACTED` | Resolves **and** is flagged retracted by ≥1 authoritative source. |
| ❌ `NOT_FOUND` | No record in Crossref/OpenAlex/PubMed — possible fabrication, typo, or non-indexed source. |
| ⚠️ `MISMATCH` | The DOI/PMID resolves, but to a **different** work (wrong or reused identifier). |
| 🔎 `LIKELY_MATCH` | A good query match with no identifier supplied — confirm it's the intended work. |
| ❓ `UNVERIFIABLE` | Grey literature (book/thesis/report) not reliably indexed by these APIs. |
| 🔌 `LOOKUP_ERROR` | Every source errored for this reference (network/rate limit) — verify manually. |

---

## Entry point (for deployment)

This is a **Path B** custom-handler agent.

| Field | Value |
|---|---|
| **Handler type** | Custom (Python) |
| **Entry file** | `handler.py` (at the repo root) |
| **Class name** | `CiteGuardHandler` |
| **Python version** | 3.10+ (developed and tested on 3.12 and 3.13) |
| **Requirements** | ships `pyproject.toml` and `requirements.txt` (`requests`, `rapidfuzz`, `bibtexparser<2`, `python-docx`) |
| **System packages** | **none** (pure pip; no `tesseract`/`ffmpeg`/etc.) |
| **Hardware** | none special (no GPU, modest RAM) |
| **Required credentials** | none. Optional: `ncbi_api_key` (raises PubMed rate limits). |
| **OASF skills** | `citeguard/verify-bibliography` (see [`agent.card.json`](agent.card.json)) |

> **Packaging note for the upload path:** the INTEGRATION_GUIDE lists `*.card.json` as a *reserved* root name for the Custom-Python upload (the system generates the card). [`agent.card.json`](agent.card.json) is included here to **document the intended skills/examples** (enter them on the registration form) and to run locally with `serve-handler --card`; exclude it from the upload archive. (Filed as repo feedback — see below.)

---

## Setup & run locally

```bash
# make `agent_skeleton` importable (the starter repo is a sibling of this one):
pip install -e ../agent-skeleton-main

# install CiteGuard's own dependencies:
pip install -r requirements.txt          # or: pip install .

# optional config (CiteGuard needs NO secrets):
cp .env.example .env                      # set CITEGUARD_CONTACT_EMAIL for polite pools + OA links
```

**Verify it works — three ways, fastest first:**

```bash
# 1. Offline unit tests (parser, matcher, verdict logic) — no network:
python -m pytest tests -q

# 2. Live end-to-end on the sample bibliography (hits the real APIs):
python examples/run_local.py               # or: python examples/run_local.py examples/sample_refs.txt

# 3. Over A2A, exactly as deployed:
python -m agent_skeleton.serve serve-handler \
    --file handler.py --class CiteGuardHandler --host 127.0.0.1 --port 9110 --card agent.card.json
python examples/a2a_smoke.py               # in another terminal (defaults to 127.0.0.1:9110)
```

The bundled [`tests/sample.bib`](tests/sample.bib) is deliberately mixed and exercises five of the seven verdicts (live output):

```
## CiteGuard: checked 6 references
**3 need attention** (1 retracted, 1 not found, 1 mismatched).
⛔ RETRACTED: 1 | ❌ NOT FOUND: 1 | ⚠️ METADATA MISMATCH: 1 | ❓ UNVERIFIABLE: 1 | ✅ VERIFIED: 2
```

- ✅ Jinek et al. 2012 (CRISPR, *Science*) → **VERIFIED**
- ⛔ Wakefield et al. 1998 (*Lancet*) → **RETRACTED** (flagged by Crossref *and* OpenAlex)
- ❌ a fabricated DOI → **NOT FOUND**
- ⚠️ a real DOI with a swapped title → **METADATA MISMATCH** (title similarity 19%)
- ✅ *Introduction to Algorithms* (a real book, no DOI) → **VERIFIED** (found in OpenAlex — grey literature is not automatically "unverifiable")
- ❓ an unpublished internal lab protocol → **UNVERIFIABLE** (not indexed anywhere — but that is *not* evidence it is fake)

---

## How it works

```
handler.py (CiteGuardHandler, Path-B adapter)
  └─ citeguard/                     ← engine; imports nothing from agent_skeleton
       parse.py    .bib/.ris/.docx/text → Reference[]  (extracts DOI/arXiv/PMID)
       clients.py  Crossref · OpenAlex · PubMed · arXiv · DOAJ · Unpaywall  (retry/backoff, polite)
       match.py    per-field rapidfuzz scoring + confidence
       verify.py   resolve → aggregate retraction signals → classify (thread-pooled)
       report.py   dual-channel: human markdown + structured dict
```

**Design choices that matter for trust:**
- **Deterministic, no LLM.** Parsing is exact; verification is API lookups + fuzzy matching. Reproducible, and it sidesteps the "no shared LLM endpoint yet" constraint entirely.
- **Retraction signals come from every source consulted.** OpenAlex `is_retracted`, PubMed publication type, and the Crossref `RETRACTED:` marker; the response lists *which* sources flagged it.
- **Multi-source, identifier-first resolution.** DOI → Crossref+OpenAlex; PMID → PubMed+OpenAlex; arXiv ID → the arXiv API (authoritative — no fuzzy matching); no identifier → Crossref bibliographic query + OpenAlex title search, then an OpenAlex retraction cross-check.
- **Blocking work runs off the event loop** (`asyncio.to_thread`) so the framework heartbeat keeps long batches alive; per-reference lookups are thread-pooled.

The title thresholds are documented in `verify.py` and echoed in the response `meta` (the author and year criteria are applied inline), so verdicts are auditable rather than magic.

---

## Repo feedback filed against the starter skeleton

Friction/bugs hit while building (see [`REPO_FEEDBACK.md`](REPO_FEEDBACK.md) for repro steps, expected vs. actual, and environment):

1. **`*.card.json` reserved-name vs. the shipped `agent.card.json`.** The starter ships `agent.card.json` at the package root, but the INTEGRATION_GUIDE lists `*.card.json` as a reserved root name for Path-B uploads — a naming collision that trips up first-time submitters.
2. **`a2a-sdk==0.3.2` emits a `StarletteDeprecationWarning`** (`HTTP_413_REQUEST_ENTITY_TOO_LARGE`) on import under current Starlette — noise on every `serve`/import; worth a pin or filter note.
3. *(Others captured during testing — see [`REPO_FEEDBACK.md`](REPO_FEEDBACK.md).)*

---

## Project layout

```
.
├── handler.py            # Path-B adapter — entry point (class CiteGuardHandler)
├── citeguard/            # deterministic verification engine (LLM-free, A2A-free)
│   ├── parse.py  clients.py  match.py  verify.py  report.py  models.py
├── tests/                # offline unit tests + sample.bib
├── examples/             # run_local.py (live) · a2a_smoke.py (over A2A) · sample_refs.txt
├── agent.card.json       # identity + OASF skill (documentation / local --card)
├── pyproject.toml  requirements.txt
├── REPO_FEEDBACK.md      # bugs/friction found in the starter
├── .env.example          # optional contact email + optional NCBI key (no secrets committed)
└── README.md
```
