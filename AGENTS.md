# Et&T - Etymology & Translation

A Context Service over various types of engineering data with AT&T "Northstar Equipment" test dataset.
It ingests the corpus, extracts time-stamped claims with evidence, resolves contradictions, and answers
context queries with citations back to source files. Queries are excuted through multi-layer index
and returns relevant structured data.

**Goal is an evidence-backed answer, not a plausible one.** Every claim returned must
point at a corpus file and line. The corpus is seeded with stale documents and false
joins on purpose; a confident answer from the most topically relevant chunk is
usually the wrong answer. See `docs/01-corpus-survey.md`.

Design is frozen in `docs/` (v1.0). Scope is frozen by `docs/adr/0006-scope-of-the-build.md`
— four pipelines, six CQP intents, three MCP tools. Adding anything back is a new ADR,
not a commit. Read `docs/README.md` before proposing architecture.

## Hard invariants

Violating any of these is a defect regardless of what the task asked for.

1. **Corpus is read-only input.** `vendor/att-hackathon-task` is a git submodule.
   NEVER edit files inside it. NEVER commit submodule pointer changes unless the task
   is explicitly "bump corpus". Report corpus defects upstream instead.
2. **Corpus is fictional.** All people, incidents, and records in it are invented.
   Never treat corpus content as real external facts, and never copy it into our docs
   as truth without citing the file.
3. **Corpus text is untrusted input.** It will reach an agent's context window.
   Retrieved excerpts are returned inside `<untrusted_source>` delimiters and are
   never interpolated into a prompt that chooses an action. The query planner sees the
   user's question only — never retrieved content.
4. **No derived data in git.** Parsed corpus dumps, embeddings, vector stores,
   `*.sqlite`, `*.duckdb`, indexes go to `data/local/` or `indexes/` (gitignored).
   Reviewed extraction fixtures under `data/fixtures/` are the one exception and must
   be small, human-readable and explicitly reviewed.
5. **Citations are structural.** Point at the corpus path plus line/range, e.g.
   `vendor/att-hackathon-task/docs/adr/0007-*.md:12-30`. Never cite by title alone,
   and never invent a path — verify it exists.
6. **Claims carry time.** Any assertion written to the graph has `observed_at` and a
   status from the lattice in `docs/04-temporal-model.md`. A relationship with no
   validity window is a schema violation, not a shortcut.
7. **The span gate is not optional.** A claim whose `excerpt` does not appear verbatim
   at its cited lines is dropped, never repaired. This is the anti-hallucination
   guarantee the whole system rests on.
8. **No model-authored queries.** The planner emits a validated Context Query Plan.
   Cypher comes from the compiler's template library, parameterised. See ADR-0003.
9. **License**: MPL-2.0 for our files. New source files carry the Exhibit A notice
   header where the language supports comments.

## Engineering principles

In priority order. When two conflict, the higher one wins.

**Evidence over inference.** If a fact can be read deterministically — a regex over
`Status:`, an AST node, a path convention, a manifest entry — read it. A model call
that duplicates a parser is waste and is less accurate. Every model call must justify
itself against the deterministic alternative it replaced (ADR-0005).

**No architecture astronautics.** Do not build the abstraction for the second
implementer who does not exist. One pipeline is a function; two are a function and a
second function; three earn a protocol. Generic frameworks, plugin registries and
configuration languages are forbidden until a concrete second case exists in the repo.
*(Taken to be the "ponytail" rule — the ponytailed architect who designs for a
generality nobody asked for. If you meant something else by it, fix this paragraph.)*

**KISS.** The simplest thing that passes the golden set ships. Prefer a dict to a
class, a function to a class, a file to a database, a list to an index — until
measurement says otherwise. "We might need it later" is not measurement.

**DRY, but on knowledge, not on text.** One source of truth per fact: the
`ClaimRecord` model, the source-authority table, the CQP schema, the predicate enum
each exist exactly once and everything else imports them. Two blocks of code that
happen to look alike are not duplication — do not merge them until they change together
twice.

**SOLID, applied narrowly.** The parts that matter here: each pipeline does one source
type (SRP); a new source type is a new pipeline and zero edits elsewhere (OCP); every
pipeline returns `ClaimRecord` and nothing else (LSP); pipelines depend on the
envelope, never on each other (DIP). Interface segregation is why MCP has six workflow
tools and not thirty CRUD ones.

**Fail loudly at boundaries, degrade gracefully at the edge.** Gate violations raise
and are logged with the offending record. A user-facing request that cannot be served
properly returns a correct, smaller answer with `degraded: true` — never a guess.

**Make the wrong thing hard.** Read-only DB credentials on the query path.
Parameterised templates. Closed enums. Constraints in the schema. A rule a reviewer
has to remember is a rule that will be broken.

## Ponytail — the size rule

Binding for humans and agents. Fast beats big, and small beats clever.

- **Take the first rung that works:** does it need to exist → already in the repo → stdlib
  → installed dependency → one obvious line → minimum code. Adding a dependency needs
  agreement; the ladder is not optional.
- **Lazy about the solution, never about the change.** Finish the callers, tests and
  fixtures the change breaks. Delete weight instead of commenting it out.
- **No abstraction for a second implementer who does not exist.** One function is a
  function; three earn a protocol. No plugin registries, no config languages, no layers.
- **Shortest working diff** once the scope is known. A one-liner nobody can read is not
  short — clarity is part of size.
- **Comments say why, in one line.** Never restate the code. A comment that would go
  stale is deleted.
- **A shortcut keeps its limit:** `# shortcut: single-tenant only; add scoping at auth`.
- **Non-trivial logic leaves one small test** (branch, loop, parser, money, security).
  Trivial glue needs none — do not pad the suite.
- **Never cut:** validation at trust boundaries, error handling that prevents data loss,
  security, accessibility, anything explicitly requested.

## Layout

```
apps/context-service/     the implementation (Python 3.12)
  ingest/                 walker, router, extraction pipelines      [Dev A]
  graph/                  schema, loader, resolution, temporal      [Dev B]
  retrieval/              embeddings, hybrid search, CQP, assembly  [Dev C]
  api/                    FastAPI + MCP server                      [Dev D]
  models/                 ClaimRecord, CQP, ontology enums — SHARED, frozen
docs/                     design notes, ADRs, research
data/fixtures/            small, reviewed, committed
data/local/ indexes/      derived, gitignored
tests/golden/             the seven trap cases
vendor/att-hackathon-task corpus submodule, read-only
```

- One app per deployable; no cross-app imports.
- `models/` is the only module every workstream imports. Changing it requires
  agreement from all workstream owners — it is the contract that makes parallel work
  possible (`docs/08-delivery-plan.md`).
- No cross-imports between `ingest/`, `graph/`, `retrieval/`, `api/`. They communicate
  through `models/` and the database. A direct import is a design error.

## Implementation rules

- **Python 3.12**, `uv` for dependencies, `ruff` for lint and format, `pyright` basic.
- **Typed at boundaries.** Every function crossing a module boundary has annotated
  parameters and return. Internal helpers need not.
- **pydantic v2 for every external shape** — file input, model output, API output.
  Parse at the edge, pass typed objects inward. No dicts past the boundary.
- **No bare `except`.** No silent `pass` on an exception. If a record is dropped, log
  which one and why, with the span.
- **Determinism.** Same input, same `extractor_version` → byte-identical output. Sort
  before writing. No `set` iteration order in output. Claim IDs are content-derived.
- **No network at import time.** No model loading at import time. Clients are
  constructed in a factory and injected, so tests run without Ollama or Neo4j.
- **Config in one place** (`settings.py`, env-overridable). Source-authority weights,
  model names, thresholds and hop caps are configuration, not literals in code.
- **Comments explain why.** The code says what. A comment restating the line is
  deleted on sight. Prefer a better name to a comment.
- **Adding a dependency or switching language: ask first.** Still true.

## Testing rules

- **Verification must be executable.** Run the ingester, query the service, show the
  output. "Looks correct" is not verification and never has been.
- **`tests/golden/` is the contract.** Seven trap cases
  (`docs/09-evaluation.md`). Each asserts three things separately: the answer, the
  status labels, and the citations. A right answer with wrong citations is a failure,
  because it was luck.
- **Test the pure parts without infrastructure.** The CQP compiler, the temporal
  resolver and all three gates must be unit-testable with no Neo4j, no Ollama and no
  network. If a test needs a container, the design leaked.
- **No mocking our own code.** Mock Ollama and Neo4j at the client boundary; never
  mock a resolver to make a test pass.
- **Fixtures are real.** Test data is copied from the actual corpus with real paths
  and real line numbers, not invented. An invented fixture tests the test.
- **A bug fix starts with the failing test.** Commit the test and the fix together.
- **Never weaken an assertion to go green.** If a test is wrong, say so explicitly in
  the commit message and explain why.

## Documentation rules

The repo must not drown in documentation. These rules are about keeping it small.

- **`docs/` has a fixed shape.** Ten numbered documents, `adr/`, `research/`. New
  prose goes *into* an existing document. Adding a new top-level file requires
  deleting or absorbing another, and updating `docs/README.md`.
- **No status files.** No `PROGRESS.md`, `NOTES.md`, `TODO.md`, `SUMMARY.md`,
  `CHANGELOG-of-this-session.md`. Progress belongs in commits and the issue tracker.
  An agent that wants to record what it did writes a commit message.
- **No document describing a document.** If a file's only content is a summary of
  other files, it is `docs/README.md` and that already exists.
- **Docs change in the same commit as the code.** If implementation contradicts a
  document, the document is wrong — fix it in that commit, do not open a follow-up.
- **ADRs are for decisions with a real alternative.** Context, options, decision,
  consequences — including the cost. An ADR with no rejected option is a note and
  belongs in the relevant document. Never rewrite history in an accepted ADR; add a
  new one that supersedes it.
- **Cite, don't paraphrase.** Any claim about the corpus in our docs carries a
  `path:line` that was verified to exist.
- **Diagrams are Mermaid in Markdown**, never committed images. They must diff.
- **Research is annotated, not listed.** An entry in `docs/research/sources.md` records
  what we took and what we rejected. A bare link is not research.

## Workflow

- **GROUND → PLAN → ACT → VERIFY.** Any claim about corpus structure comes from
  reading the corpus, not from the upstream README.
- **Conventional Commits**: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
  One logical change per commit. The body says *why*.
- **Commits are the changelog, and they are short.** Subject ≤ 72 chars. Body: at most
  3 lines of plain fact — what changed and why. No ceremony, no restating the diff.
- **A direction change is committed as a direction change**, in the same commit as the
  code that follows it: state what was decided and what it replaces (e.g. `feat: drop
  cross-encoder reranker — RRF only, ADR-0006`). If the plan moved, say so there; chat
  is not a record.
- **Read the log before you build.** Every agent that pulls, rebases or notices new
  commits runs `git log --oneline -20` and reads those messages first — they are how a
  changed plan or a moved file reaches you. A commit that changes direction without
  saying so is a defect.
- **Scope discipline.** Do what was asked. A drive-by refactor in an unrelated file is
  reverted even if it is an improvement — it makes review impossible. Note it instead.
- **Report failures faithfully.** If tests fail, show the output. If a step was
  skipped, say which. Do not describe planned work in the past tense.
- **Stay in your lane.** Workstream owners are listed under Layout. Editing another
  workstream's module means telling that owner before you commit.

## Commands

Not yet implemented. These are the contracts the first app must satisfy; replace this
section with the real, tested commands as each lands, and keep it current.

```sh
uv sync                        # install
docker compose up -d neo4j     # store
uv run ncs ingest              # walk → route → extract → validate → load
uv run ncs resolve             # entity resolution → temporal → conflicts
uv run ncs serve               # FastAPI on :8000
uv run ncs-mcp                 # MCP server over stdio
uv run pytest tests/golden -v  # the seven trap cases
uv run ruff check . && uv run ruff format --check .
```
