# CiteGuard

Run your reference list past the databases that actually know whether a paper exists. CiteGuard reads a bibliography and checks every citation against Crossref, OpenAlex, PubMed, and arXiv. For each one it tells you whether it resolves to a real record and whether the details you typed actually match that record. It also catches the citations nobody wants to miss: the retracted ones, and the ones that were quietly made up.

It's an [A2A](https://a2a-protocol.org/) agent built on the DTRC starter skeleton, and it runs as a Path B custom handler. Give it a `.bib`, `.ris`, or `.docx` file, or paste a list straight into the message. Every verdict links to a real record you can open yourself, or it says plainly that nothing turned up. No LLM runs anywhere in the pipeline, so the same bibliography always produces the same result.

---

## Start here: the six questions

Every DTRC submission has to answer these, so here they are up front.

**1. What research workflow does it improve?**

The last check before a reference list leaves your hands. Before a manuscript or a grant goes out, someone's supposed to confirm that every citation points to a real paper whose details match the record, and that none of them have been retracted. In practice that means opening DOIs one at a time, and it's dull enough that people skip it. The risk went up once drafting with LLMs became normal, because those models invent citations that read perfectly and lead nowhere. CiteGuard clears the whole list in one pass.

**2. Who at WashU would benefit?**

- Grad students and PIs putting the last polish on something they're about to submit.
- Reviewers who want a quick integrity pass on a paper they've been handed.
- Research admins and grants managers checking a proposal's citations before it goes out.
- Becker Medical Library folks who help authors and run systematic reviews.

**3. What does it do that a general chatbot would not?**

A chatbot will cheerfully confirm a paper that doesn't exist, and it has no idea what got retracted last week. CiteGuard won't call anything real unless a database hands back a matching record, and it reads retraction status straight from the source. It also catches something a chatbot can't: a real, working DOI pasted onto the wrong title. That last one is a classic sign a citation was fabricated or copied carelessly.

**4. What is it designed to handle well?**

Prompts like:

- "Verify the references in my attached `.bib` file."
- "Check this reference list for anything retracted or made up." (then paste it)
- "Do all the DOIs in my bibliography actually point to the right papers?"

It handles mixed lists too, with journal articles sitting next to arXiv preprints next to books. And it's built to fail gracefully. Send it nothing and it asks for a file or a list. Upload something it can't parse and it flags that one file instead of falling over. Give it a citation with no identifier and it either finds the match by searching or marks it `NOT_FOUND`. It never guesses.

**5. What tools and APIs does it use?**

Inputs are `.bib`, `.ris`, `.docx`, or pasted text. Everything it queries is free and needs no key:

- **Crossref** for metadata and Retraction-Watch retraction signals
- **OpenAlex** for `is_retracted`, cross-checks, and title-search recall
- **PubMed** (E-utilities) for biomedical retractions via publication type
- **arXiv** for resolving arXiv IDs exactly
- **DOAJ** and **Unpaywall** for the extras, meaning open-access journal listing and open-access links

Matching runs on `rapidfuzz`. Nothing else, and no other agents.

**6. How does it handle uncertainty, privacy, credentials, and limitations?**

Uncertainty shows up in the open. Every verdict carries per-field match scores and a link to the record, so you can judge it yourself. A shaky match gets labeled `LIKELY_MATCH`, never `VERIFIED`.

It's careful about not overclaiming. A `VERIFIED` needs more than one field to agree, so a lucky title match can't quietly bind a fake citation to some real paper. Retraction only gets asserted from authoritative fields, and it's confirmed across more than one source.

On privacy, the only things that leave your machine are identifiers, titles, author names, and years. Your manuscript text stays put, and every response says so.

Credentials aren't required at all. There's one optional NCBI key that bumps up PubMed's rate limit, read from `context["credentials"]` when deployed or from `NCBI_API_KEY` locally. It's never written into the code.

The limits are stated in the output itself. CiteGuard tells you a citation is real, unretracted, and a metadata match. It does not tell you whether the source is any good or whether you've read it right. Books, theses, and reports often aren't indexed, so they come back `UNVERIFIABLE` rather than wrong. And a journal missing from DOAJ isn't evidence of anything shady.

---

## Input and output

**In:** one or more `.bib` / `.ris` / `.docx` files, a pasted reference list, or both at once.

**Out:** the usual two-channel A2A response.

- `answer` is human-readable markdown. It opens with a one-line summary, then lists references grouped by verdict with the problems first, each showing its record link, match scores, and any notes. A short footer covers data handling and limits.
- The structured `DataPart` is there for another agent or tool to pick up:
  - `summary`: counts per status (`RETRACTED`, `NOT_FOUND`, `MISMATCH`, `LIKELY_MATCH`, `UNVERIFIABLE`, `LOOKUP_ERROR`, `VERIFIED`, `TOTAL`)
  - `references`: one object per citation with `status`, `confidence`, `input`, `matched_record` (source, DOI, URL, `is_retracted`, `retraction_sources`, OA URL), `match_scores`, `sources_checked`, and `notes`
  - `meta`: which sources were consulted, the thresholds used, and the data-flow disclosure

### The verdicts

| Status | What it means |
|---|---|
| ✅ `VERIFIED` | Resolves to a real record, and the metadata agrees. |
| ⛔ `RETRACTED` | Resolves, and at least one authoritative source flags it retracted. |
| ❌ `NOT_FOUND` | Nothing in Crossref, OpenAlex, or PubMed. Could be fabricated, a typo, or just not indexed. |
| ⚠️ `MISMATCH` | The DOI or PMID resolves, but to a different paper. Wrong or reused identifier. |
| 🔎 `LIKELY_MATCH` | A decent match found by search, with no identifier to confirm it. Worth a look. |
| ❓ `UNVERIFIABLE` | Grey literature (a book, thesis, or report) that these databases don't index reliably. |
| 🔌 `LOOKUP_ERROR` | Every source errored on this one, usually network or rate limit. Check it by hand. |

---

## Deploying it

It's a Path B custom-handler agent. Here's what the DTRC team needs.

| Field | Value |
|---|---|
| Handler type | Custom (Python) |
| Entry file | `handler.py` (at the repo root) |
| Class name | `CiteGuardHandler` |
| Python version | 3.10 or newer. Tested on 3.12 and 3.13. |
| Requirements | `pyproject.toml` and `requirements.txt` ship with it: `requests`, `rapidfuzz`, `bibtexparser<2`, `python-docx` |
| System packages | none. It's pure pip, no `tesseract` or `ffmpeg` or anything like that. |
| Hardware | nothing special. No GPU, modest RAM. |
| Required credentials | none. An optional `ncbi_api_key` raises PubMed's rate limit. |
| OASF skills | `citeguard/verify-bibliography` (see [`agent.card.json`](agent.card.json)) |

One packaging heads-up. The INTEGRATION_GUIDE treats `*.card.json` as a reserved name for the Custom-Python upload, since the system generates the card itself. The [`agent.card.json`](agent.card.json) here is for documenting the skill and examples (type them into the registration form) and for running locally with `serve-handler --card`. Leave it out of the upload archive. It's written up in the repo feedback below.

---

## Running it locally

```bash
# make agent_skeleton importable (it's the starter repo, a sibling of this one):
pip install -e ../agent-skeleton-main      # or wherever the starter lives

# CiteGuard's own dependencies:
pip install -r requirements.txt            # or: pip install .

# optional, and there are no secrets involved:
cp .env.example .env                       # set CITEGUARD_CONTACT_EMAIL for the polite pools and OA links
```

Three ways to see it work, quickest first:

```bash
# 1. Offline unit tests. No network. Covers parsing, matching, and the verdict logic:
python -m pytest tests -q

# 2. Live run on the sample bibliography (this one hits the real APIs):
python examples/run_local.py               # or point it at examples/sample_refs.txt

# 3. Over A2A, the way it actually deploys:
python -m agent_skeleton.serve serve-handler \
    --file handler.py --class CiteGuardHandler --host 127.0.0.1 --port 9110 --card agent.card.json
python examples/a2a_smoke.py               # from another terminal
```

The [`tests/sample.bib`](tests/sample.bib) file is rigged to hit every verdict. Here's what comes back:

```
## CiteGuard: checked 6 references
**3 need attention** (1 retracted, 1 not found, 1 mismatched).
⛔ RETRACTED: 1 | ❌ NOT FOUND: 1 | ⚠️ METADATA MISMATCH: 1 | ❓ UNVERIFIABLE: 1 | ✅ VERIFIED: 2
```

- ✅ Jinek et al. 2012 (CRISPR, *Science*) comes back **VERIFIED**
- ⛔ Wakefield et al. 1998 (*Lancet*) comes back **RETRACTED**, flagged by both Crossref and OpenAlex
- ❌ a made-up DOI comes back **NOT FOUND**
- ⚠️ a real DOI with the wrong title on it comes back **MISMATCH** (title similarity 19%)
- ✅ *Introduction to Algorithms*, a real book with no DOI, comes back **VERIFIED** because OpenAlex has it. Grey literature isn't automatically unverifiable.
- ❓ an unpublished internal lab protocol comes back **UNVERIFIABLE**, which isn't the same as fake

---

## How it works

```
handler.py  (CiteGuardHandler, the Path-B adapter)
  └─ citeguard/                    the engine; imports nothing from agent_skeleton
       parse.py    .bib/.ris/.docx/text  ->  Reference[]   (pulls out DOI/arXiv/PMID)
       clients.py  Crossref · OpenAlex · PubMed · arXiv · DOAJ · Unpaywall  (polite, retry/backoff)
       match.py    per-field rapidfuzz scoring and confidence
       verify.py   resolve, gather retraction signals, classify  (thread-pooled)
       report.py   the two channels: human markdown plus a structured dict
```

A few decisions carry the trust story.

**No model, on purpose.** Parsing is exact and verification is API lookups plus fuzzy matching, so runs are reproducible. It also means CiteGuard doesn't care that there's no shared LLM endpoint yet.

**Retraction gets cross-checked, not taken on one source's word.** The signals come from OpenAlex's `is_retracted`, PubMed's publication type, and the `RETRACTED:` marker Crossref puts on titles. The response names which sources flagged it.

**Identifiers first, always.** A DOI goes to Crossref and OpenAlex. A PMID goes to PubMed and OpenAlex. An arXiv ID goes to the arXiv API, which is exact, so there's no fuzzy guessing. Only when there's no identifier at all does it fall back to a Crossref search plus an OpenAlex title search, and even then it re-checks retraction on whatever it finds.

**Slow work stays off the event loop.** The blocking lookups run in a thread pool through `asyncio.to_thread`, which keeps the framework's heartbeat alive on long lists.

The title, author, and year thresholds live in `verify.py` and get echoed back in the response `meta`, so you can see why a verdict landed where it did instead of taking it on faith.

---

## Repo feedback for the starter skeleton

Things I ran into while building this. Full repro steps, expected-vs-actual, and environment are in [`REPO_FEEDBACK.md`](REPO_FEEDBACK.md).

1. **The `*.card.json` name clashes with the shipped file.** The starter ships `agent.card.json` at the root, yet the INTEGRATION_GUIDE lists `*.card.json` as reserved for Path-B uploads. A first-time submitter can't tell which one wins.
2. **`a2a-sdk==0.3.2` warns on import.** You get a `StarletteDeprecationWarning` about `HTTP_413_REQUEST_ENTITY_TOO_LARGE` every time you import or serve. It's harmless but noisy, and worth a pin or a filter.
3. A few smaller ones are written up in the same file.

---

## What's in here

```
.
├── handler.py            # the Path-B adapter and entry point (class CiteGuardHandler)
├── citeguard/            # the verification engine (no LLM, no A2A imports)
│   ├── parse.py   clients.py   match.py   verify.py   report.py   models.py
├── tests/                # offline unit tests, plus sample.bib
├── examples/             # run_local.py (live), a2a_smoke.py (over A2A), sample_refs.txt
├── agent.card.json       # identity and the OASF skill (docs, and local --card)
├── pyproject.toml        # packaging and dependencies
├── requirements.txt      # the same deps, for pip install -r
├── .env.example          # optional contact email and NCBI key, no real secrets
├── REPO_FEEDBACK.md      # bugs and friction found in the starter
└── README.md
```
