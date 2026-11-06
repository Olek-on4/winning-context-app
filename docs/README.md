# Northstar Context Service — design documentation

Design record for an evidence-backed, time-aware Context Service over the
`vendor/att-hackathon-task` corpus.

Read in order. Each document is load-bearing; there is no overview-of-the-overview.

| # | Document | Answers |
|---|----------|---------|
| 00 | [brief.md](00-brief.md) | What was asked, and how it is scored |
| 01 | [corpus-survey.md](01-corpus-survey.md) | What is actually in the corpus, and where it lies to you |
| 02 | [architecture.md](02-architecture.md) | The system, end to end |
| 03 | [ontology.md](03-ontology.md) | How knowledge is represented |
| 04 | [temporal-model.md](04-temporal-model.md) | How "valid / deprecated / planned" is decided |
| 05 | [extraction-pipelines.md](05-extraction-pipelines.md) | How each source type is read |
| 06 | [retrieval.md](06-retrieval.md) | How a question becomes a safe query |
| 07 | [api-and-mcp.md](07-api-and-mcp.md) | How agents and humans connect |
| 08 | [delivery-plan.md](08-delivery-plan.md) | Who builds what, in what order, in 5 hours |
| 09 | [evaluation.md](09-evaluation.md) | How we know it works, and what it cannot do |
| 10 | [workstreams.md](10-workstreams.md) | Who builds what, and what each lane hands over |

Supporting material:

- [adr/](adr/) — decisions with their alternatives and trade-offs.
- [research/sources.md](research/sources.md) — annotated bibliography behind the design.
- [plan-review.html](plan-review.html) — visual review of this design: pillars, mechanics,
  the five-hour timeline, and the findings that must close before implementation.
  Open it in a browser; every card and table row is annotatable.

## Status

Version 1.0 — **frozen for implementation**, 2026-11-06. Scope and the five blockers
from the review are settled in [ADR-0006](adr/0006-scope-of-the-build.md); nothing else
may be added without a new ADR. Not yet implemented.
Every document below is a *claim about what we will build*. When implementation
disagrees with a document, the document is wrong: fix it in the same commit.
Open findings from [plan-review.html](plan-review.html) are tracked in
[10 — workstreams](10-workstreams.md#who-owns-which-review-finding).
