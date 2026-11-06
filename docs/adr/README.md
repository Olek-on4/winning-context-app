# Architecture decisions

One file per decision that had a real alternative. Format: context, options,
decision, consequences. If a decision had no plausible alternative it does not get an
ADR — it goes in the document it belongs to.

| # | Decision | Status |
|---|---|---|
| [0001](0001-single-store-neo4j.md) | Neo4j as the single store for graph, vector and full-text | Accepted |
| [0002](0002-reified-claims.md) | Reify claims instead of asserting triples | Accepted |
| [0003](0003-cqp-not-cypher.md) | Planner emits a validated query plan, never Cypher | Accepted |
| [0004](0004-no-llm-index-layer.md) | No LLM at index time; defer to query time | Accepted |
| [0005](0005-local-models-deterministic-first.md) | Local models, deterministic-first extraction | Accepted |
| [0006](0006-scope-of-the-build.md) | Scope of the build: what ships, what is documented | Accepted |
| [0007](0007-quality-filter.md) | Quality filter: contradiction-relative freshness and a verdict split | Accepted |
