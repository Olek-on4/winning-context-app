# ADR-0002 — Reify claims instead of asserting triples

Date: 2026-11-06
Status: Accepted

## Context

An extractor reading `docs/adr/004-people-sso.md` finds a proposed identity bridge
between employee and customer accounts. The document explicitly states it *"must not
be interpreted as an approved SSO rollout."* A plain property graph offers two
options: assert `(People)-[:USES_SSO]->(Accounts)`, which is false, or drop it, which
loses the fact that someone is actively proposing it.

The same problem recurs for every contradiction, every hypothesis (SEC-22's suspected
authorisation gap), and every superseded fact (the Redis cache).

## Options

1. **Direct triples** with properties for time and confidence.
2. **Reified claims** — a `Claim` node per assertion, with entities and relationships
   derived from claims by a resolver.
3. **Named graphs / quads** — one subgraph per source.

## Decision

**Reified claims (option 2)**, with a materialisation step that promotes resolved
claims into direct relationships for traversal speed.

Option 1 cannot represent two sources disagreeing without either picking a winner at
extraction time — far too early, before the resolver has seen the ADR that settles
it — or storing both and leaving consumers to guess. Option 3 handles provenance but
not modality: it can say *the wiki says X*, not *this is a proposal that forbids being
read as a decision*.

## Consequences

- Extraction becomes dumb and parallel; all judgement moves into one resolver that is
  deterministic and unit-testable. This is also what lets four developers work
  independently.
- Every answer can show who asserted what, when, and who disagreed.
- Cost: three hops per logical hop when traversing claims, and roughly 3–5× the node
  count. Mitigated by materialising resolved relationships at L2 with `DERIVED_FROM`
  back-links — fast path and audit path in the same graph.
- Claims are never deleted. The graph grows monotonically; `DEPRECATED` is a state,
  not a tombstone.
