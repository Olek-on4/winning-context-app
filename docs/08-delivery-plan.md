# 08 — Delivery plan: four developers, five hours

## The budget problem, stated plainly

Four developers × five hours = **20 developer-hours**, minus setup, minus
integration, minus the demo rehearsal. Realistically ~14 hours of productive build.

The design in documents 02–07 is a two-week system. It does not fit, and pretending
otherwise is how teams arrive at the demo with four half-finished branches and
nothing that runs.

So this plan does something specific: it **ships a narrow spine that proves the
thesis end to end**, and treats the rest of the design as the documented forward
path. That is not a compromise forced on us — it is the scoring-optimal move. 45 of
100 points are Presentation and Forward View, which reward a clearly explained
design; Knowledge Representation (25) is substantially won by
[03](03-ontology.md) and [04](04-temporal-model.md) existing and being coherent.
Extraction (15) and Connection (15) need *working* code, but working on a narrow
slice, not on everything.

**The one thing that must work on stage:** ask the service whether stock uses a Redis
cache, and watch it answer "no, removed 2026-06-04", cite ADR-003 and release 1.3,
and label the wiki page `DEPRECATED` — then watch an IDE agent decline to
reintroduce `REDIS_URL` because of it.

Everything below exists to make that true, honestly, from real extraction.

## Scope line

Frozen by [ADR-0006](adr/0006-scope-of-the-build.md). Column 1 is the build; column 2 is
the same lanes working faster, not extra scope; column 3 is a slide.

| Must ship (the spine) | Should ship (if ahead) | Will not ship (documented, not built) |
|---|---|---|
| Neo4j Community + uniqueness constraints | `/v1/gaps`, `/v1/conflicts` | L3 community layer |
| Config, Schema, ApiSpec pipelines | Security sub-extractor (`context_risks` corroboration) | Cross-encoder reranker |
| Narrative **header** pass (dates/status, no LLM) | Narrative LLM claim extraction | CodePipeline (tree-sitter) |
| Claim loader + gates 1–3 | `LOOKUP` + `TIMELINE` intents | DiagramPipeline VLM (fixtures instead) |
| Entity + temporal resolver steps 1–6, conflicts | OTel tracing | `IMPACT_OF_CHANGE` intent and tool |
| Hybrid search (vector + BM25 + RRF) | | Injection scanner, `ncs verify`, `--since` |
| CQP: `STATE_OF`, `RELATIONSHIP`, `CONFLICTS`, `RISKS` | | Auth, multi-tenant |
| MCP: 3 tools · REST `/v1/query`, `/v1/plan`, `/v1/span` | | |
| Golden set of 7 traps, green | | |

Anything in column 3 that a developer "just quickly adds" is a bug in this plan, not
a bonus. Say so out loud at the checkpoint.

## Contracts are loaded, not designed

They are written **before** the event — no corpus, no Neo4j and no model is needed for
any of them ([10](10-workstreams.md#the-four-contracts-frozen-before-the-event)). The first
30 minutes are for loading them into four checkouts and proving they agree:

1. `ClaimRecord` pydantic model ([05](05-extraction-pipelines.md#one-envelope-six-pipelines--four-ship)) — **frozen**.
2. `cqp.schema.json` ([06](06-retrieval.md#the-cqp-schema)) — **frozen**, six intents.
3. `answer.schema.json` ([06](06-retrieval.md#answer-assembly)) — **frozen**, referential citations.
4. `schema.cypher` — uniqueness constraints only, Community-safe ([03](03-ontology.md#storage-indexing-and-validation-in-neo4j)).
5. `data/fixtures/claims-sample.jsonl` — 30 hand-written ClaimRecords covering traps
   T1 and T2.

`docker compose up -d neo4j` must be green on all four laptops by 00:20; a laptop that
cannot start the store is found then, not at 02:40.

Item 5 is what actually buys the parallelism: with sample claims on disk, B, C and D
never wait for A's extractors. This is contract-first development applied to a data
pipeline ([sources](research/sources.md#contract-first)) and it is the only reason four
people on one five-hour system is not worse than two.

**A contract change after 00:20 requires all four to agree, in person.** A silent
envelope change is the failure mode that ends this.

## Workstreams

```mermaid
gantt
    dateFormat HH:mm
    axisFormat %H:%M
    title Five hours, freeze at 03:30
    section All
    Contracts loaded            :done, c, 00:00, 20m
    Checkpoint 1 (integrate)    :milestone, m1, 02:00, 0m
    Checkpoint 2 (feature freeze):milestone, m2, 03:30, 0m
    Demo rehearsal              :crit, dr, 03:30, 45m
    section A · Ingest
    Walker + router             :a1, 00:20, 40m
    ConfigPipeline              :a2, after a1, 60m
    SchemaPipeline              :a3, after a2, 45m
    Gate audit + integration    :a4, after a3, 35m
    section B · Knowledge
    Neo4j schema + loader       :b1, 00:20, 60m
    Entity resolution           :b2, after b1, 45m
    Temporal resolver 1–6       :crit, b3, after b2, 60m
    Conflict detection          :b4, after b3, 15m
    section C · Retrieval
    Embeddings + hybrid search  :c1, 00:20, 60m
    Wire prebuilt compiler      :crit, c2, after c1, 60m
    Templates + assembler       :c3, after c2, 60m
    section D · Edge + proof
    Fixtures + answer schema    :d1, 00:20, 40m
    REST skeleton               :d2, after d1, 60m
    FastAPI + MCP server        :crit, d3, after d2, 60m
    Golden set + demo script    :d4, after d3, 30m
```

### Dev A — Ingest and extraction
**Owns** `apps/context-service/ingest/`.
Walker (`git ls-files` + content hash), content router, `ConfigPipeline`,
`SchemaPipeline`, then the gate audit that proves every record passes 1–3. No tree-sitter, no VLM —
[ADR-0006](adr/0006-scope-of-the-build.md).
**Done when** `ncs ingest` writes a `claims.jsonl` whose every record passes gates 1–3,
including the `users.status → account_status` rename (trap T2) from the real migration.
**Depends on** nothing after minute 30. Hands off a file.

### Dev B — Knowledge representation and time
**Owns** `apps/context-service/graph/`.
Neo4j schema, claim loader (`MERGE` on derived id), entity resolution cascade,
**temporal resolver**, conflict detection.
**Done when** loading `claims-sample.jsonl` yields a graph where the Redis
relationship is `DEPRECATED` with `valid_to=2026-06-04` and a `SUPERSEDES` edge from
ADR-003 — and the wiki claim is still present and queryable.
**This is the critical path.** The resolver is where the system's whole argument lives.
If Dev B slips, everyone else has a working demo of a search engine.

### Dev C — Retrieval and query planning
**Owns** `apps/context-service/retrieval/`.
Embedding client (Ollama), chunker, hybrid search + RRF, CQP validator, compiler,
three templates, answer assembler with citations.
**Done when** `POST /v1/execute` with a hand-written CQP returns the T1 answer
envelope from [06](06-retrieval.md#answer-assembly), citations included.
**Note:** build the compiler before the planner. A working compiler with hand-written
plans is a complete demo; a planner with no compiler is nothing. If the local model
disappoints, we demo with stored plans and explain the split — which is a *stronger*
story about error-proofing, not a weaker one.

### Dev D — Edge, proof and presentation
**Owns** `apps/context-service/api/`, `tests/golden/`, the deck.
Diagram fixtures (hand-extract the six PNGs, 20 min), narrative header pass,
FastAPI, MCP server, golden-set harness, demo script, slides.
**Done when** Claude Code can call `context_search` and get the T1 answer, and
`pytest tests/golden` prints 7 rows with pass/fail per trap.
**Dev D owns the 35-point area.** That is deliberate: presentation is the largest
single block of marks, and assigning it to "whoever finishes first" is how teams lose
it. Dev D is building the thing being judged.

## Integration checkpoints

**Checkpoint 1 — 02:00. Integrate whatever exists.** Real claims from Dev A loaded by
Dev B, queried by Dev C, served by Dev D. It will be thin. That is fine; the point is
that the seams are proven while there is still time to fix them. Teams that integrate
at hour four discover their envelope mismatch at hour four.

**Checkpoint 2 — 03:45. Feature freeze.** No new capability after this. The remaining
75 minutes are integration, the golden set, and rehearsal. Anything incomplete is
`git stash`-ed and described as forward work, not demoed half-working.

## Demo script

Seven minutes, rehearsed twice, in this order — the first two minutes carry the marks.

1. **The problem, from the corpus** (45s). Show `wiki/inventory-service.md:5` and
   `docs/adr/003-stock-cache.md:6` side by side. "Both of these are in the repo. One
   is wrong. Nothing in the repository says which."
2. **Naive retrieval fails** (30s). Vector search for "stock cache" → the wiki page,
   ranked first, confidently.
3. **The service answers** (90s). `context_search` → "No, removed 2026-06-04", with
   ADR-003 + release 1.3 citations, the wiki claim labelled `DEPRECATED`, and the
   supersession chain.
4. **The IDE loop** (90s). In Claude Code: "add a cache to the stock read path."
   The agent calls the tool and declines, citing ADR-003.
5. **The ontology, in one slide** (60s). Three planes, four layers, why claims rather
   than triples.
6. **Time travel** (45s). Same question with `as_of: "2026-03-01"` → "yes, Redis."
   Same graph, different clock. This is the moment that lands the bi-temporal model.
7. **Limitations and forward view** (60s). Read from
   [09](09-evaluation.md#limitations). Naming our own weaknesses before a judge does
   is worth more than one more feature.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Local model too slow/weak for claim extraction | **High** | Spine uses deterministic pipelines only. LLM extraction is in column 2. Fixtures guarantee a demo. |
| Temporal resolver (Dev B) slips | Medium | Fixtures let C and D finish regardless; A can take resolver steps 1–3 if idle at CP1. |
| Neo4j vector index setup burns an hour | Medium | Dev C validates it in the first 30 min, on real data, before building anything on it. |
| Envelope drift between A and B | Medium | One pydantic model, imported by both. Gate 1 fails loudly at the boundary. |
| Scope creep into column 3 | **High** | Checkpoint 2 is a hard stop. Column 3 is a *slide*, not a branch. |
| Demo machine has no Neo4j / no Ollama | Low | Rehearse on the actual demo machine before 04:15, not on a laptop that works. |
