# ADR-0006 — Scope of the build: what ships, what is documented

Date: 2026-11-06
Status: Accepted

## Context

The design in `docs/02`–`07` is a two-week system; the budget is 4 developers × 5 hours.
The review of that design (`docs/plan-review.html`) found five blockers, three of which
were scope: a critical path with zero slack, a six-tool MCP surface where the plan
shipped three, and a retrieval pipeline whose diagram included a reranker the plan had
already cut. No implementation exists yet, so an incoherent document is free to fix and
expensive to discover later.

## Decision

Freeze a **four-pipeline, five-intent, three-tool** service and move everything else to
the forward view. Specifically:

**Ships**

- Pipelines: `ConfigPipeline`, `SchemaPipeline`, `ApiSpecPipeline`,
  `NarrativePipeline` (deterministic header pass only — dates, statuses, path rules).
- Resolver: identity (declared identifiers), temporal (7 steps), conflicts.
- Store: Neo4j Community, uniqueness constraints only.
- Retrieval: vector kNN + BM25 → RRF → compile → traverse → assemble.
- Intents: `LOOKUP`, `STATE_OF`, `RELATIONSHIP`, `CONFLICTS`, `TIMELINE`, `RISKS`
  (six; `IMPACT_OF_CHANGE` is cut — it is the only template needing reverse closure).
- MCP tools: `context_search`, `context_explain_relationship`, `context_risks`.
- REST: `/v1/query`, `/v1/plan`, `/v1/execute`, `/v1/entity/{kind}/{key}`, `/v1/span`.
- Golden set: seven traps, three assertions each.

**Documented, not built** (each already had a named owner or column in `docs/08`)

- `CodePipeline` (tree-sitter, five grammars) — the largest single build, and T1's
  corroboration already arrives from ADR-003 + release 1.3 + the September diagram.
  Dynamic dispatch and string-built URLs were its weak points anyway.
- `DiagramPipeline` VLM extraction — replaced by six human-committed fixtures under
  `data/fixtures/diagrams/`, which is what a real deployment would do at the accuracy
  the literature reports.
- L3 topic/community layer (Leiden), noun-phrase community labels.
- Cross-encoder reranking.
- `IMPACT_OF_CHANGE` intent and `context_impact_of_change` tool.
- `/v1/gaps`, `/v1/conflicts`, `/v1/timeline`, OTel tracing, the prompt-injection
  scanner, `ncs verify`, `ncs ingest --since`, auth, multi-tenancy.

## Consequences

- Extraction drops to deterministic parsing only, so the model is used in exactly two
  places: modality classification and CQP planning. Both are classification tasks.
- The stale-documentation story is unaffected: T1 resolves from ADR-003's negation plus
  release 1.3, neither of which needs code parsing.
- The security scenario weakens: `context_risks` reports SEC-22 as `DISPUTED` from the
  issue record alone, without the corroborating static-analysis claim. Reported as one
  signal, not as a finding — which is the honest state of that trap anyway.
- Two endpoints that a judge may ask for (`/v1/gaps`, `/v1/conflicts`) exist only as
  documented forward work. Say so before being asked.
- Diagrams and code facts become forward view, so "we parse five languages" is not
  claimable on the day. The ontology and temporal model carry those 25 points instead.
