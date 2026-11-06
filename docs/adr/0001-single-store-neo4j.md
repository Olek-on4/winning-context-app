# ADR-0001 — Neo4j as the single store

Date: 2026-11-06
Status: Accepted

## Context

The service needs three access patterns over the same knowledge: graph traversal
(impact analysis, relationship paths), dense vector similarity (semantic search), and
lexical search (exact identifiers — `REDIS_URL`, `cus-001`, `account_status`, port
numbers). The corpus is 374 files / 3.3 MB; the architecture must be credible at a
thousand times that.

## Options

1. **Neo4j alone** — native HNSW vector index and Lucene full-text alongside Cypher.
2. **Postgres + pgvector + recursive CTEs** — one store, no graph engine. Measured at
   0.34/0.42/0.95 ms p50 for 1/2/3 hops and genuinely sufficient below ~10k nodes /
   50k edges, which is our corpus.
3. **Graph DB + separate vector DB** (Qdrant/LanceDB) — best-of-breed each.
4. **Kùzu** — embedded, no server, fastest path queries.

## Decision

**Neo4j 5.x alone.**

Option 3 is rejected outright: two stores means a sync problem, and a context service
whose own index can go stale relative to itself is self-defeating. Option 4 is
rejected on maintenance risk — the upstream repository was archived on 2025-10-10 and
is read-only following an acquisition. Option 2 is the strongest alternative and we
record it as such; the team chose Neo4j for Cypher's legibility in a seven-minute
demo and for the fact that the traversal-plus-vector query is a single statement.

## Consequences

- One `docker compose up`, one connection, one backup.
- Hybrid retrieval is one Cypher statement: vector kNN seeds, traversal expands,
  temporal predicates filter. No application-side join between stores.
- We accept a JVM and ~1 GB of RAM as a dependency, where options 2 and 4 are lighter.
- If Neo4j's vector index underperforms at scale we can externalise vectors without
  changing the ontology, since `Chunk.embedding` is a property and not a schema.
