# consensus: land `feat/quality-filter` as focused PRs, not a second tree

Cross-lane. Owner: Dev on `feat/quality-filter` (reply on this issue).

## Problem

`main` and `origin/feat/quality-filter` forked at `761f5d6` (2026-11-06 12:10) and both
built the whole app from there. Adopting the branch wholesale deletes a verified path;
merging both means reconciling two `ClaimRecord` models and two `cli.py`.

## Evidence

```
$ git merge-base main origin/feat/quality-filter   → 761f5d6  docs: freeze v1.0 scope
$ git diff --name-only main...origin/feat/quality-filter | wc -l   → 43
$ git diff --name-only origin/feat/quality-filter...main | wc -l   → 48
$ git diff --name-status main...origin/feat/quality-filter | head
A  apps/context-service/cli.py          # also on main, different content
A  apps/context-service/models/claim.py # second claim model
A  apps/context-service/graph/scoring.py
A  apps/context-service/ingest/gates.py
A  apps/context-service/ingest/dates.py
A  apps/context-service/ingest/headers.py
A  apps/context-service/settings.py
```

`docs/consensus.md` §2 already proposes the resolution: `main` is canonical for the
interfaces, and the branch's work lands as one-concern PRs.

## Change (branch side)

1. Rebase the branch on current `main`; drop files that duplicate `main` wholesale
   (`cli.py`, `models/claim.py`, `mcp_server.py`, `service.py`) rather than reconciling them.
2. Land three PRs, in this order:
   - `ingest/gates.py` wired as a registry step — span verification before the loader.
     `main` has no excerpt gate; only per-pipeline line lookup.
   - `ingest/dates.py` + `ingest/headers.py` — declared status and modality capping,
     consumed via `registry._claim(...)`.
   - `graph/scoring.py` — review against `graph/resolver.py` + ADR-0008 instead of
     re-landing; say in the PR where the resolver is wrong if it is.
3. Answer the three questions in `docs/consensus.md` §"Questions I cannot answer alone" on
   this issue, especially **Q1**: does the gate layer replace `loader.assert_loadable` or run
   before it? One is simpler; both is defensible and we should pick one in writing.

## Acceptance

- `make check` green on the rebased branch.
- One PR per concern above, each touching only its own lane's files.
- No second `ClaimRecord`, no second CLI.
