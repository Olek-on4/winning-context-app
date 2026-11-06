# 10 — Workstreams: four developers, four lanes

Four lanes, one owner each, one contract between them. This supersedes the workstream
section of [08](08-delivery-plan.md#workstreams) where they disagree — the split is the
same shape, but the timing reflects the two schedule defects found in review
([timeline](08-delivery-plan.md#workstreams) ends exactly at the freeze; conflict
detection ran past it).

Budget: 4 × 5 h = 20 developer-hours, ~14 productive. Freeze at **03:30**, not 03:45.
The 15 minutes recovered are the only slack in the plan.

## The four lanes

| Lane | Owner | Owns | Never touches |
|---|---|---|---|
| **Extraction** | Dev A | `apps/context-service/ingest/` | `graph/`, `retrieval/`, `api/` |
| **Core** | Dev B | `apps/context-service/graph/`, `infra/neo4j/` | `ingest/`, `retrieval/`, `api/` |
| **Search** | Dev C | `apps/context-service/retrieval/` | `ingest/`, `graph/`, `api/` |
| **MCP / API** | Dev D | `apps/context-service/api/`, `apps/context-service/mcp/`, `tests/golden/`, `data/fixtures/` | the three above |

Boundary rule: a cross-lane change is a message to the owner, not a commit. The only
shared artefacts are the four contracts below; both sides of a contract change together
or not at all.

## The four contracts (frozen 00:00–00:20, all four present)

Each contract already has a defining section; the freeze only turns prose into code.
Anchor lines were re-checked on 2026-11-06.

| Contract | Defined by | State |
|---|---|---|
| `contracts/claim.py` — `ClaimRecord` + `Span` | [05:6-32](05-extraction-pipelines.md#one-envelope-six-pipelines) | text complete, plus the two precision fields |
| `contracts/cqp.schema.json` | [06:39-85](06-retrieval.md#the-cqp-schema) | text complete, needs JSON Schema form |
| `contracts/answer.schema.json` | [06:122-156](06-retrieval.md#answer-assembly) | **only an example exists** — no schema, no field list; D writes it first |
| `infra/neo4j/schema.cypher` | [03:157-190](03-ontology.md#storage-indexing-and-validation-in-neo4j) | text complete, minus the Enterprise-only constraints |

Plus one artefact that buys the parallelism: `data/fixtures/claims-sample.jsonl`,
30 hand-written claims covering T1 and T2. Dev C and Dev D develop against it from
minute 20; without it they wait two hours for Dev A.

**Two fixes to the contracts found in review:**

- `ClaimRecord` gains `valid_from_precision: date | month` and `observed_precision`,
  because `releases/2026-06-v1.3.md` yields `2026-06` and the time-travel demo filters on
  `valid_from <= t`. Normalise to the **first day of the period**; record that you did.
- `schema.cypher` uses **uniqueness constraints only**. Property existence
  (`REQUIRE … IS NOT NULL`) is Enterprise Edition in Neo4j 5; the compose file does not
  say which edition it pulls. Non-null is enforced in pydantic and the loader instead.
  If someone insists on Enterprise, it goes in `infra/neo4j/compose.yaml` with a licence
  note — one decision, written down, not discovered at 02:40.

## Lane detail

### A · Extraction — `ingest/`

Owns the walker, the router and the deterministic pipelines. Works entirely on files;
never opens Neo4j.

- **00:20–01:00** Walker (`git ls-files` + content hash), router (path → extension →
  magic bytes), `ConfigPipeline` (`package.json`, `compose.yaml`, `config/ports.json`,
  `pnpm-workspace.yaml`, `turbo.json`, `CODEOWNERS`).
- **01:00–02:00** `SchemaPipeline` (`sqlglot`): migration-ordered validity —
  `002-account-tiers.sql` closes `users.status`, opens `users.account_status`.
- **02:00–03:00** `NarrativePipeline` **header pass only** — `Date:`, `Status:`,
  bylines, filename dates, `api-specs/history/` and `archive/` path rules. No model.
- **03:00–03:30** integration fixes against the loader.

**Gate 2 is A's responsibility and it needs a mechanism, not a hope.** Chunks handed to
any model must carry line numbers, and the record must be produced as
`excerpt + start_line`; the pipeline derives `end_line` from the match offset. Excerpt
absent → drop the claim and count it.

**Done when** `uv run ncs ingest` writes `data/local/claims.jsonl` and
`uv run python -m ingest.audit data/local/claims.jsonl` prints every record passing
gates 1–3, including the `users.status → account_status` rename from the real migration.

### B · Core — `graph/` + `infra/neo4j/`

Owns the store, the loader and every decision about what is currently true.

- **00:20–00:50** Neo4j up on all four laptops; `schema.cypher` applied; edition
  decision recorded in the compose file comment.
- **00:50–01:50** Loader: `MERGE` on the derived claim id, `DERIVED_FROM`,
  `EVIDENCED_BY`, idempotent re-runs.
- **01:50–03:00** Temporal resolver steps 1–7 (`04`): score, explicit supersession,
  negation, prohibition, ranking, ties, corroboration. Pure functions over a list of
  claims — testable without Neo4j, so it is unit-tested against T1 by 02:30.
- **03:00–03:30** Conflict detection (`CONTRADICTS`, both sides kept) and L2
  materialisation of only the claims that survived.

**Owns the edition risk.** If Community is the only option on the demo machine, the
fallback is already decided above; nobody discovers it live.

**Done when** `uv run ncs resolve` turns fixtures + ingested claims into a graph where
T1 answers `DEPRECATED` for the wiki claim with `valid_to=2026-06-04`, and running the
loader twice leaves the node count unchanged.

### C · Search — `retrieval/`

Owns the only path from a question to the database. Highest risk, longest chain, so
**the compiler and the seven templates are written before the event** — they need no
corpus, no Neo4j and no model, and writing them on the day is what puts the freeze at
risk.

- **Pre-event** `cqp.schema.json`, the validator, the seven compiler templates, the
  assembler. Unit tests with hand-written plans as fixtures.
- **00:20–01:20** Embeddings (`nomic-embed-text`, 768-d) over chunks; hybrid seed —
  vector kNN + BM25 → RRF (k=60). No cross-encoder: it is not in the five-hour build,
  and the recall target gets set for the pipeline that actually ships.
- **01:20–02:40** Wire plan → compile → execute → assemble against the real graph.
  Planner failures degrade to hybrid-only with `degraded: true` — never a guess.
- **02:40–03:30** Token budget + ordering (`06`), `conflicts` and `gaps` in the
  envelope, latency measured warm.

**Done when** `uv run pytest tests/cqp` is green with no model running, and
`curl -s localhost:8000/v1/plan -d '{"question":"does inventory use redis?"}'` returns a
valid CQP with `intent=STATE_OF`.

### D · MCP / API — `api/`, `mcp/`, `tests/golden/`, `data/fixtures/`

Owns the two transports, the proof, and the demo.

- **00:20–01:00** Fixtures (30 claims, T1 + T2), the acceptance envelope, and a REST
  skeleton answering from fixtures — so the demo shape exists at 01:00 regardless of
  what the graph can do.
- **01:00–02:00** `ContextService` service layer; `/v1/query`, `/v1/plan`, `/v1/execute`,
  `/v1/entity/{kind}/{key}`.
- **02:00–03:00** MCP server, **three** tools: `context_search`,
  `context_explain_relationship`, `context_risks`. Six are documented, three ship —
  say that out loud rather than shipping three and describing six.
- **03:00–03:30** Golden set of seven traps, three assertions each (answer, status,
  citation). Freeze at 03:30 whether or not all seven are green; the run is the report.

**Done when** `uv run pytest tests/golden -v` prints seven rows and the MCP server
answers `context_search` from Claude Code with citations.

## Dependency graph

```mermaid
flowchart LR
    subgraph T0["00:00 – 00:20 · all four"]
        K["contracts + fixtures"]
    end
    K --> A
    K --> B
    K --> C
    K --> D
    A["A · extraction<br/>claims.jsonl"] --> B["B · core<br/>graph + status"]
    B --> C["C · search<br/>plan → answer"]
    C --> D["D · MCP/API<br/>tools + proof"]
    D -.->|"fixtures unblock"| C
    C -.->|"answer envelope"| D
```

Only A→B and B→C are real waits, and both consume a **file**, not a running service.
C's pre-built compiler means its wait starts at 01:20, not at 00:20.

## Checkpoints

| Time | Gate | Fails if |
|---|---|---|
| 00:20 | Contracts frozen, fixtures on disk, Neo4j up | anyone still designing an interface |
| 02:00 | One pipeline → graph → `/v1/query` answers T1 from real data | the path is still fixture-only |
| 03:30 | Feature freeze; golden set run and printed | someone is mid-refactor |
| 03:30–04:15 | Rehearsal on the demo machine | rehearsal starts on a laptop |
| 04:15 | Demo | — |

Column 3 of the scope line ([08](08-delivery-plan.md#scope-line)) is a slide, not a
branch. Anything unfinished is stashed and described as forward work.

## Who owns which review finding

| Finding | Owner | Closed by |
|---|---|---|
| Pack §3/§4 unknown | team lead, before 00:00 | both sections in hand, diffed against the must-ship column |
| Zero-slack critical path | C | compiler + templates pre-built |
| Gate 2 mechanism unspecified | A | line-numbered chunks, derived `end_line` |
| Month-precision dates | B | `*_precision` fields, first-day convention |
| Neo4j Enterprise-only constraints | B | uniqueness-only schema or enterprise compose |
| 6 vs 3 tools | D | three shipped, six documented |
| Reranker cut but still in docs | C | shipped pipeline stated as vector + BM25 + RRF |
| Spine vs design indistinguishable | all | one-line `spine: yes/no` marker per section |
| `06` cites app.py:41-58 | D | corrected to 61-85 in the same commit as the fixture |
