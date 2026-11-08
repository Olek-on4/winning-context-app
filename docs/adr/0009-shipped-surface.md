# 0009 — The shipped surface, and the scope it re-opened

Status: Accepted (supersedes nothing; extends [0006](0006-scope-of-the-build.md))

## Context

ADR-0006 froze four pipelines, six intents and three MCP tools, and deliberately left
several capabilities described-but-unbuilt: an ontology gate, an API-spec pipeline, and
the `/v1/execute`, `/v1/entity`, `/v1/sources`, `/v1/index/status`, `/readyz` routes. The
review found the documents still presenting those as shipped, which is worse than either
having them or not having them: a reader cannot tell which claims are true.

## Options

1. **Delete the descriptions.** Docs follow code; the gap between promise and product
   disappears by lowering the promise. Cheapest, and it keeps ADR-0006 intact.
2. **Build the missing pieces.** Restores the promise, costs roughly a day, and grows the
   surface every future maintainer has to keep working.
3. **Build the cheap ones, delete the rest.** Mixed, and leaves two standards for the same
   question.

## Decision

Option 2, for the parts that are deterministic and need no new dependency:

- **Ontology gate** (`ingest/ontology.py` + `PREDICATES` in `settings.py`): predicate must
  exist in the taxonomy and the subject/object kinds must satisfy its declared domain and
  range. Runs on the same path as the span gate, and `cli load` reports
  `ontology_rejected`.
- **ApiSpecPipeline** (`api.spec`): OpenAPI `paths` and GraphQL SDL fields become `EXPOSES`
  claims; `history/` and `archive/` are `HISTORICAL` at authority 0.20.
- **Five routes**: `/v1/execute` (validated CQP, never caller Cypher), `/v1/entity/{kind}/{key}`,
  `/v1/sources`, `/v1/sources/{path}`, `/v1/index/status`, `/readyz`.

Rejected explicitly: `sqlglot` for the schema pipeline (a dependency and a parser to
recover facts two anchors already recover), `contracts/` as a second copy of the models
(one fact, one file), and the endpoint/handler gap detector (needs the code pipeline that
ADR-0006 cut).

## Consequences

- **The frozen scope is no longer frozen.** This ADR records that, instead of pretending
  otherwise; anything further is a new ADR, not a commit.
- The ontology table is now a gate: a predicate absent from `settings.PREDICATES` is
  rejected, so a new pipeline must declare its vocabulary before it can write claims.
  That is the cost of the guarantee, and it is paid in one file.
- `/v1/execute` widens the attack surface slightly: it accepts a plan from the caller. It
  still validates and compiles that plan, so the caller chooses the question, never the
  query — the property ADR-0003 exists to preserve.
- The docs now distinguish built from designed in the same sentence, which is the state
  this ADR was written to reach.
