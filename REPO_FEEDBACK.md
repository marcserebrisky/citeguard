# Starter-repo feedback (from building CiteGuard)

Findings hit while building a **Path B** agent on `agent-skeleton`. Each has repro
steps, expected vs. actual, environment, and a suggested fix. File these as GitHub
issues/PRs against the starter repo.

**Environment (all findings):** macOS (Darwin 25.5), Python 3.13.5,
`agent-skeleton==0.1.0` installed `-e`, `a2a-sdk[http-server]==0.3.2`,
`starlette==1.3.1`, `pydantic==2.13.4`.

---

## 1. `*.card.json` is a reserved upload name, but the starter ships `agent.card.json` at root  ·  *medium*

**What:** `INTEGRATION_GUIDE.md` §4 lists reserved root names for the Custom-Python
(Path B) upload archive: `agent_skeleton/`, `Dockerfile`, and **`*.card.json`**
("the system generates those"). But the starter itself ships `agent.card.json` at
the package root, and `README.md`/`CLAUDE.md` present it as a file you edit.

**Repro:**
1. Follow Path A docs → you edit `agent.card.json`.
2. Switch to Path B and package for upload per INTEGRATION_GUIDE §4.
3. If you zip the project contents (the documented, natural thing to do), the
   archive contains `agent.card.json`.

**Expected:** clear guidance on whether a Path-B submission may/should include a
`*.card.json`, and where skills come from.
**Actual:** the reserved-name rule silently conflicts with the shipped file name;
a first-time submitter can't tell if their upload will be rejected or the file
ignored.
**Suggested fix:** either rename the Path-A example (e.g. `agent.card.example.json`)
or add a one-line note in INTEGRATION_GUIDE §4 — "if you built on Path A, exclude
`agent.card.json` from the Path-B upload; declare skills on the form instead."

---

## 2. `a2a-sdk==0.3.2` emits a `StarletteDeprecationWarning` on import  ·  *low*

**What:** importing anything that pulls `agent_skeleton.serve` prints a
`StarletteDeprecationWarning: 'HTTP_413_REQUEST_ENTITY_TOO_LARGE' is deprecated`
from inside `a2a/server/apps/jsonrpc/fastapi_app.py`.

**Repro:**
```bash
python -c "import agent_skeleton.serve"
```
**Expected:** clean import.
**Actual:**
```
.../a2a/server/apps/jsonrpc/fastapi_app.py:21: StarletteDeprecationWarning:
'HTTP_413_REQUEST_ENTITY_TOO_LARGE' is deprecated. Use 'HTTP_413_CONTENT_TOO_LARGE' instead.
```
**Cause:** the exact pin `a2a-sdk==0.3.2` resolves against a newer Starlette that
deprecated the constant a2a-sdk 0.3.2 still uses.
**Suggested fix:** note the warning is benign in the README's "Gotchas", or bump/
re-pin `a2a-sdk`, or pin Starlette to a compatible range.

---

## 3. Mutable default argument `files: list[FileInput] = []` in the `AgentHandler` contract  ·  *low*

**What:** `base.py` defines both `handle_structured(self, user_input, files=[], ...)`
and `handle(self, user_input, files=[])` with a mutable default list. The
INTEGRATION_GUIDE template copies the same pattern. It's the classic shared-mutable-
default anti-pattern (benign only because the list is never mutated), and linters
(Ruff `B006`, Pylint `W0102`) flag it in every handler users copy from the docs.

**Repro:** `ruff check --select B006 base.py` (or copy the doc template and lint it).
**Expected:** the canonical contract users clone doesn't ship a lint-flagged pattern.
**Actual:** `B006 Do not use mutable data structures for argument defaults`.
**Suggested fix:** use `files: list[FileInput] | None = None` and normalize with
`files = files or []` inside the body (this repo's `handler.py` does exactly that).

---

*Add further findings here as they come up during testing.*
