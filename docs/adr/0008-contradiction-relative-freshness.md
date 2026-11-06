# ADR-0008 — Contradiction-relative freshness

Date: 2026-11-06
Status: Accepted

## Context

`score = authority × extractor confidence` alone lets a June ADR lose to an October
commit that merely implements it, and lets a wiki page nobody has contradicted age into
irrelevance. The corpus makes this concrete: git stamps every file `2026-10-22`
(`git log -1 --format=%cs`), so every code fact looks newer than the decision governing
it.

Absolute decay is wrong in both directions: it punishes ADR-003 for being four months
old while it is still the current decision, and it demotes every old fact nobody has
disputed.

## Options

1. **No decay** — status alone decides. Simple; the tie margin does all the work.
2. **Absolute decay** — score halves with age relative to today. Penalises correct old
   decisions and rewards recently touched files for no semantic reason.
3. **Contradiction-relative decay** — a claim decays only by how much *newer a
   contradicting claim* is, with a floor. Undisputed facts keep 1.0.

## Decision

**Option 3.** In [`graph/resolver.py`](../../apps/context-service/graph/resolver.py):

```
freshness = max(0.25, 0.5 ** ((newest_rival_date − valid_from).days / 180))
```

`newest_rival_date` is the newest claim of the opposite polarity about the same triple.
No rival, or a rival older than the claim → 1.0. The decayed score is stored on the claim
so an audit can see it.

Ported from `feat/quality-filter` (ADR-0007), kept without that branch's settings layer:
two constants, no config module.

## Consequences

- A stale wiki page still loses to the ADR that removed the thing, by score *and* by
  negation; freshness only widens the gap for genuinely old contradictions.
- An old, uncontested fact is not penalised for age — which is the difference between
  "stale" and "settled".
- The half-life and floor are guesses. They are named constants, not spread through the
  code, and the resolver test pins the direction of the effect rather than the exact
  number.
