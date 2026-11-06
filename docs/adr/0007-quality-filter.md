# ADR-0007 — Quality filter: contradiction-relative freshness and a verdict split

Date: 2026-11-06
Status: Accepted

## Context

The resolver in [04](../04-temporal-model.md#resolution-algorithm) gives every claim a
status. Two questions were open. First: should the *date* a source was published move
its score, beyond what supersession already does? Second: how should an answer separate
what an agent may use from what it may not, so that a chat or IDE agent repeats only
current facts while still knowing what is stale?

The corpus constrains both. The git history of `vendor/att-hackathon-task` stamps every
file 2026-10-22 (`git log --format=%cs`), so a code or config fact always looks newer than
the ADR that decided it. And a lone wiki claim nobody contradicts is status `VALID`,
which an agent reading only statuses would repeat as fact.

## Options

**Freshness**

1. *None* — `score = authority × time_confidence × extractor_confidence`, as in 04 v1.0.
   Simple. Leaves equal-authority conflicts decided by the tie margin alone.
2. *Absolute decay* — score halves with age relative to today. Penalises ADR-003
   (June) against the git-dated code that implements it (October), and penalises
   every old fact nobody has disputed.
3. *Contradiction-relative decay* — a claim decays only by how much **newer a
   contradicting fact** is, with a floor. Undisputed facts keep 1.0.

**Answer split**

1. *One `claims` list with statuses* (06 v1.0) — the agent filters.
2. *Hide everything not `VALID`* — the agent cannot explain why the wiki disagrees.
3. *Two lists by verdict* — `claims` (status `VALID` and `confidence ≥ min_confidence`)
   and `not_valid` (everything else, labelled with a reason).

## Decision

Freshness option 3: `freshness = max(0.5, 0.5^(Δdays / 120))`, Δ measured to the newest
later contradicting `FACT`/`DECISION` in the same triple. Answer option 3, with the verdict
as one function of three ordered checks (status, `min_confidence`, `min_source_types`)
whose first failure is reported as `filtered_by`. Per-source-type and per-document-status
rules are rows in two tables (`SOURCES`, `DOC_STATUSES`), so every kind of data — diagram,
wiki, API spec, issue — passes the same filters; the resolver never names a type. All
constants are in `settings.py`.

## Consequences

- An old, uncontested fact is not weakened by age; a claim that newer evidence argues
  with is, which is the only case where age carries information.
- Freshness rarely changes a status on its own: supersession and the `supersede_ratio`
  guard do the deciding. It moves scores in genuine conflicts and in the reported
  confidence, and so moves the `tie_margin` outcome — that is its purpose.
- Agents get a rule they cannot misread: use `claims`, warn with `not_valid`. The cost is
  that a true but thinly evidenced fact (one wiki page, 0.32) is withheld as
  `LOW_CONFIDENCE` until a second source type agrees. We accept false negatives here
  over a confident wrong answer.
- `min_confidence` is now the single most consequential number in the answer path. It
  is configuration, and `uv run ncs resolve` shows what every claim scores against it.
