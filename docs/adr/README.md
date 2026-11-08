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
| [0006](0006-scope-of-the-build.md) | Scope of the build: four pipelines, six intents, three tools | Accepted |
| [0008](0008-contradiction-relative-freshness.md) | Contradiction-relative freshness | Accepted |
| [0009](0009-shipped-surface.md) | The shipped surface, and the scope it re-opened | Accepted |
| [0010](0010-semantic-claims-and-effort.md) | Claims searchable by meaning; an `effort` knob that widens recall only | Accepted |
| [0011](0011-evidence-layer.md) | The envelope carries cited evidence, not only claims | Accepted |
| [0012](0012-diagram-evidence.md) | Diagram evidence: deterministic geometry first, a model last | Proposed |
| [0013](0013-opt-in-capabilities.md) | Opt-in capabilities and the licence boundary | Accepted |
