# ADR-0003 — The planner emits a query plan, never Cypher

Date: 2026-11-06
Status: Accepted

## Context

The requirement is that a user query be translated into *concrete, error-proof
instructions*. The obvious implementation is Text2Cypher. The 2026 literature on
Text2Cypher is a catalogue of its failure modes — syntax errors, schema mismatch —
and of mitigations layered on to contain them: grammar-aware filtering, schema
filtering, confidence-based decoding, execution validation, self-refinement loops.

We are also running a local 7–8B model, which is the weakest realistic generator.

## Options

1. **Text2Cypher** with the published mitigation stack.
2. **A fixed set of parameterised queries** selected by intent classification.
3. **Context Query Plan** — the model fills a JSON Schema-validated plan; a
   deterministic compiler emits parameterised Cypher from a template library.

## Decision

**Option 3.**

Option 1's mitigation stack is evidence against the approach: every layer exists to
contain an output space that did not need to be unbounded. Option 2 is safe but
cannot express anchors, hop budgets, or time filters without a combinatorial explosion
of templates. The CQP keeps the template library small (seven intents) while letting
the model supply the variable parts — which reduces its job to classification and
slot-filling, the thing small models are actually good at.

## Consequences

- A syntax error cannot reach the database. Invalid plans fail at the validator.
- The compiler is pure, so the entire query layer has millisecond unit tests with no
  model — decisive under a five-hour budget with four people integrating.
- Cypher injection is absent rather than mitigated; templates are read-only,
  hop-capped and row-capped.
- The planner is swappable: a local model, a frontier model, or a hand-written plan
  from `curl` all enter through the same validated door.
- **Cost: expressiveness.** A question whose shape has no template cannot be answered
  exactly; it degrades to hybrid search with `degraded: true` in the response. We
  judge an honest degraded answer better than a confidently wrong traversal.
