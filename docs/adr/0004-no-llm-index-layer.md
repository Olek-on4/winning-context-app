# ADR-0004 — No LLM at index time for the topic layer

Date: 2026-11-06
Status: Accepted

## Context

The multilayer index needs a topic/community layer (L3) so that broad questions can
be scoped before traversal. Microsoft GraphRAG builds this with LLM-generated
community summaries at index time.

We have local models and five hours.

## Options

1. **Full GraphRAG** — LLM entity extraction plus LLM community summaries at index time.
2. **LazyGraphRAG** — non-LLM graph construction; all LLM use deferred to query time
   under a relevance-test budget.
3. **No topic layer** — anchor and traverse only.

## Decision

**Option 2.** Noun-phrase extraction and co-occurrence build the concept graph; graph
statistics and Leiden produce hierarchical communities; no model runs at index time.

Microsoft's published numbers decide it: LazyGraphRAG's indexing cost is identical to
plain vector RAG and 0.1% of full GraphRAG, while matching GraphRAG global search on
quality at roughly 4% of its query cost. The justification they give is the one that
applies hardest to us — most pre-computed community summaries are never queried.

Option 3 was tempting for a five-hour build, but without a topic layer the only
retrieval entry point is an exact anchor, and "what's related to the stock area?" has
no answer.

## Consequences

- Index time is embedding-bound, not generation-bound. A full re-index stays minutes.
- Query cost scales with the relevance-test budget, a single tunable knob.
- Community labels are extractive (top terms) rather than fluent prose. Acceptable:
  the label is a navigation aid, not an answer.
- L3 is nonetheless first out of scope under time pressure
  ([08](../08-delivery-plan.md#scope-line)) — it is the cheapest layer to build and
  the least necessary for the demo.
