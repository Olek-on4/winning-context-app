# ingest: derive supersession from `api-specs/history/` and `archive/` paths

Lane A (Extraction). Owner: unclaimed.

## Problem

`ingest/registry.py` ships three pipelines — `SqlAlter`, `JsonConfigMap`, `MarkdownStatus` —
and none of them reads the path. Supersession and archive status reach the graph only through
the reviewed fixtures in `data/fixtures/claims-sample.jsonl`, so traps G3 and G5 pass on
hand-written data, not on extraction.

## Evidence

```
$ cd apps/context-service && uv run python -m cli extract
{"claims": 28, ...}
$ uv run python -c "from ingest.deterministic import ...; print(sorted({c.predicate for c in extract(CORPUS)}))"
['HAS_COLUMN', 'HAS_DATE', 'HAS_OWNER', 'HAS_STATUS', 'LISTENS_ON']
```

`grep -n 'history\|archive' ingest/registry.py` → no match. The corpus carries
`api-specs/history/accounts-v1.md` and `archive/conference-registration/README.md`, and
`docs/10-workstreams.md` §A allocates 02:00–03:00 to exactly this "header pass".

## Change

One pipeline that matches on path segment:

- any file under `api-specs/history/` → claims it describes are `SUPERSEDED` by the current
  sibling under `api-specs/`, `valid_to` = the history file's own `Date:` when present;
- any file under `archive/` → `archive` scope, never `VALID` as current state.

Keep emit shape `ClaimRecord`; the resolver already handles supersession by score
(`graph/resolver.py`, ADR-0008), so no core edit is needed if the claim carries
`observed_at` and a `HAS_STATUS`/endpoint negation the resolver can rank.

## Acceptance

- `cli extract` on the submodule alone yields a `DEPRECATED`-able claim citing
  `api-specs/history/accounts-v1.md`, with no fixture present.
- `tests/test_agnostic.py` stays green: the new pipeline must key off path shape, not off
  the name `att-hackathon-task`.
