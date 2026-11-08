# 0010 — Search the graph by meaning, and let a number say how hard to look

Status: Accepted (extends [0009](0009-shipped-surface.md); supersedes nothing)

## Context

Measured on the live stack: a question that named nothing the extractors recognised
returned zero claims. The embedding work was not at fault — the chunk hits existed and were
written into `gaps` as *"No claims matched; evidence candidates were a.md, b.md, c.md"*.
Only claims are answerable, so semantic retrieval was paid for and thrown away.

Two candidate answers to "find something even when no term was extracted":

1. **Promote chunk hits to claims.** Cheapest, and it breaks the contract the product is
   built on: a chunk is unverified corpus prose, a claim is a triple with a status, a
   validity window and a span-verified citation. The whole point of the corpus is that the
   topically nearest text is often the stale one.
2. **Search claims by meaning.** Embed each claim's *statement* (`subject PREDICATE
   object`), never its excerpt, and query that vector index with the plan's own status and
   time filters. Costs one more vector index and one embed per query.

## Decision

Option 2, plus a caller-visible number.

- **`claim_embedding`** (`graph/claims_embed.py`): `cli index` embeds all 311 claims.
  `build()` reports `offered` *and* `matched`, because an earlier version counted only the
  first and printed `claim_vectors: 311` while the graph held none.
- **`effort: int 0..4`** on the query plan, semi-automatic: the planner starts at 1 when the
  question names an identifier and 2 when it names nothing; the caller may pin any level.
  Each level pays for a wider claim-vector search and *caps* what it returns — 2, 3, 4, 5
  claims for levels 1–4. Every level runs the identical status, time, confidence and span
  gates, so effort widens recall only. It cannot make a weaker answer into a stronger one.
- Missing embedder, unbuilt index or flat scores fall back to the exact graph pass silently
  — a quieter answer, never a failed one.

## Consequences

- Measured ladder on `"what cases are we covering"` (names nothing, no key in the corpus):
  `effort 0 → 0 claims`, `1 → 2`, `2 → 3`, `3 → 4`, `4 → 5`. The default 2 answers a
  question that previously returned nothing.
- **Precision is the cost.** Claim statements score 0.72–0.84 with almost no spread, so
  similarity orders poorly. A floor (0.70) removes junk, but only the per-level cap keeps a
  vague question from returning a pile of real-but-unrelated facts. The `gaps` line
  *"Widened by meaning: N more claim(s)"* is the honesty mechanism, and it is why the
  envelope needs no new field.
- 311 more vectors and one embed call per widening. On this corpus the `llama3.2` planner
  is still not pulled, so planner provenance stays `deterministic` while the semantic
  channel works; the two use different models and fail independently.
- The seven traps remain 7/7: they all name identifiers, so they start at effort 1 and
  never widen.
