# ADR-0005 — Local models, and deterministic extraction first

Date: 2026-11-06
Status: Accepted

## Context

The team will have Ollama and local open-weight models on hackathon day: no API key,
no per-call cost, no rate limit, and no network dependency. The trade is capability —
a 7–8B model hallucinates predicates, invents subjects, and is markedly worse at
diagram understanding than the frontier models whose benchmark numbers are already
only ~70% on architecture diagrams.

The brief anticipates exactly this: *"Participants may have different levels of access
to LLM and VLM models. Therefore, the most important judging criterion is not only the
output itself, but how clearly the team explains the engineering and AI thinking."*

## Decision

Local models via Ollama, and **every model call must justify itself against a
deterministic alternative.** Where a regex, an AST parse or a path rule can produce
the fact, it does.

Model calls are confined to three places:

1. Claim extraction from narrative prose (constrained by JSON Schema at generation).
2. Modality classification — six-way, genuinely linguistic.
3. CQP planning — classification and slot-filling, not generation.

Everything else — dates, statuses, schema changes, dependencies, ports, workspace
membership, path-based deprecation — is deterministic.

## Consequences

- The demo runs offline with no key and no spend. It cannot be broken by a rate limit
  on stage.
- Accuracy on the highest-value facts is *higher* than an LLM-first design would
  achieve, because `Status: Accepted` parsed by a regex beats any model reading it.
- The span gate ([03](../03-ontology.md#storage-indexing-and-validation-in-neo4j))
  carries the quality burden for the LLM path: claims whose quoted evidence is not
  literally in the file are dropped. We expect to discard a meaningful fraction and
  consider that the system working.
- Recall from the narrative pipeline is unmeasured and probably poor. Named as a
  limitation in [09](../09-evaluation.md#limitations) rather than hidden.
- Upgrading to a frontier model is a config change, not a redesign — which is the
  property the brief's note about unequal access actually rewards.
