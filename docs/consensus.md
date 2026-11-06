# Consensus — how `main` and `feat/quality-filter` become one system

Written 2026-11-06 by the `main` side. This is the proposal to review, not a decision
made about your work. Where I disagree with the branch, the evidence is a file and a line.

## What `main` is today

| Fact | Evidence |
|---|---|
| 72 tests, 0 lint findings | `make check` |
| Seven corpus traps answered end to end | `uv run pytest tests/golden -v` |
| Cold start rehearsed from an empty graph | `scripts/rehearse.py` → `rehearsal: READY` |
| Data-agnostic ingestion | `sources.py` + `ingest/registry.py`; any directory is a root, pipelines self-register |
| Client-agnostic transports | `models/protocols.py::ContextBackend`; `api/` and `mcp_server/` import neither `retrieval` nor `graph` |

## The conflict, stated plainly

`feat/quality-filter` is a second implementation, not an addition on top of `main`:

- it replaces `models/claim.py`, `cli.py` and `mcp_server/`,
- it deletes `infra/neo4j/compose.yaml`,
- it splits resolution into `graph/resolve.py` + `graph/scoring.py` beside our
  `graph/resolver.py`,
- its `ingest` reads `data/fixtures/claims-sample.jsonl` and enriches it (gates, dating,
  modality caps) rather than extracting from the corpus.

Adopting it wholesale would delete a verified path; merging both means reconciling two
`ClaimRecord` models. Neither is a decision to make by accident.

## Proposal (what I am asking you to agree to)

1. **`main` is canonical for the interfaces.** `ClaimRecord`, `Span` (pointer, not prose),
   `ContextBackend`, `sources.Root`/`SpanStore`. One claim model in the repo.
2. **Your work lands as focused PRs**, each touching one concern:
   - `ingest/gates.py` — span verification and excerpt hints, wired as a
     `registry.Pipeline` step that rejects claims before they reach the loader. This is the
     piece `main` does not have and the corpus most needs.
   - `ingest/dates.py` + `ingest/headers.py` — declared status and modality capping,
     consumed by pipelines through `registry._claim(...)`.
   - `graph/scoring.py` — already ported in spirit: `main` has contradiction-relative
     freshness in `graph/resolver.py` and [ADR-0008](adr/0008-contradiction-relative-freshness.md).
     Review that diff instead of re-landing the whole module; if it is wrong, say where.
3. **Open an issue per disagreement**, not a parallel file. Two implementations is how a
   five-hour budget turns into a merge conflict at the worst moment.

## What I will do in return

- Keep `docs/adr/` as the decision log: your ADR-0007 becomes the reference for the
  freshness work, and ADR-0008 records what was actually built.
- Publish interfaces before changing them: `models/protocols.py` and `sources.py` are the
  seam; a PR that changes either says so in its title.
- Apply the same gate to my own work: `make check` runs on every commit for everyone
  (`git config core.hooksPath .githooks`).

## Questions I cannot answer alone

1. Is the gate layer in `feat/quality-filter` meant to replace the loader's
   `assert_loadable`, or to run before it? Both is defensible; one is simpler.
2. Your `ExtractedClaim` model carries `EvidenceHint` (a quote plus a line hint). Do you
   want that as the pipeline output shape — i.e. pipelines emit hints and the gate turns
   them into `Span`s — or do pipelines resolve spans themselves?
3. Anything in your branch that you consider load-bearing and that the list above
   undersells. Name it and it goes first.

## How to reply

Issue on this repository, or a PR that changes exactly one of the files in §2. If you
prefer a synchronous decision, the checklist above is short enough to settle in one pass:
agree, or name the item you reject and why.

## Status since the fork — 2026-11-06, `main` side

Fork point is `761f5d6` (12:10). `main` is now `ce026ec`; the branch forked before any of
the application code existed, so **both sides wrote `cli.py`, `models/claim.py`,
`mcp_server`, `service.py` independently** — 43 files only there, 48 only here. Nothing in
§2 has changed; issue 06 in `scripts/issues/` is the branch-side work list.

What `main` now does, all verified by command today (Windows-free, RTX 3060, 6 GB):

| Claim | Evidence |
|---|---|
| 7 corpus traps green end to end | `uv run pytest tests/golden -q` → 7 passed |
| Full gate | `uv run pytest -q` → 73 passed, `ruff check .` clean |
| Cold-start rehearsal | `uv run python ../../scripts/rehearse.py` → `rehearsal: READY`, 12/12 |
| Model-backed retrieval live | 1119 of 1119 chunks carry a 768-d vector; `via: bm25+vector` on T1 |
| Query latency | `/v1/query` 10 ms, `degraded: false` |

Three defects fixed after the fork, each with a regression test or a reproducible command:

1. `409b1ff` — `graph/chunks.py` computed embeddings and discarded them (0 of 1119 stored),
   and hashed a per-body index so 434 of 1119 windows collided onto one id. The vector
   channel was dead while `cli index` reported `embedded: true`.
2. `48ceabc` was reverted in `ba8db13`: the golden fixture never needed a chunk index.
   Answers come from compiled CQP rows (`service.py` uses hybrid only at lines 99 and 116,
   for gap text), and with indexing disabled all seven traps still pass. The three failures
   that motivated it came from a probe wiping the graph while the suite was mid-run.
3. `0d2eda9` — a model-first planner lost traps G3 and G7 and invented `as_of=2022-01-01`
   for an undated question, silently filtering out every current claim. Planning is now
   deterministic-first; the model is the fallback for questions that name no anchor.

Read these before rebasing: the failure modes above are the ones a second implementation
will reproduce, because they are in the retrieval and planner seams, not in extraction.

## Questions still open

§"Questions I cannot answer alone" is unchanged and still blocks the gate layer. Q1 is the
one to settle first: if `ingest/gates.py` runs *before* `loader.assert_loadable`, the loader
stays the non-null guarantee and the gate only rejects spans; if it replaces the loader,
`ClaimRecord` and the loader both lose a check. Pick one and write it in the PR title.
