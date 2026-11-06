# golden: stop the trap fixture from wiping the shared graph

Cross-cutting (tests + Core). Owner: unclaimed.

## Problem

`tests/golden/test_traps.py` runs `MATCH (n) DETACH DELETE n` on the `neo4j` database it is
pointed at. That deletes the chunk index too — 1119 chunks with 768-d vectors — so a single
`make test` after `make index` leaves the demo answering from an empty retrieval layer until
someone re-runs `cli index`. It also means the suite and any other writer share one graph: a
probe that wipes and reloads mid-run makes the traps fail for reasons that have nothing to do
with the code under test. That is exactly what happened on 2026-11-06 and cost one wrong
commit (`48ceabc`, reverted in `ba8db13`).

## Evidence

```
$ cd apps/context-service && grep -n 'DETACH DELETE' tests/golden/test_traps.py
50:        session.run("MATCH (n) DETACH DELETE n").consume()

$ uv run python -m cli index && uv run pytest tests/golden -q
$ uv run python - <<'PY'
# after the suite: chunks embedded drops from 1119 to 0
PY
```

With `index_chunks` in the fixture removed, all seven traps still pass — the claims come from
compiled CQP rows, not from chunks — so rebuilding the index there was never the fix.

## Change

- Give the integration tests their own database (`neo4j` supports multiple databases in
  Community; `NEO4J_DB` env or `connect(..., database="test")`) and create it once in the
  fixture, or
- scope the wipe to the labels the fixture writes: `MATCH (c:Claim|Span|Entity) DETACH DELETE c`,
  leaving `Chunk`/`Source` untouched.
- Either way the fixture must announce which database it uses in its docstring, and the
  rehearsal must not share it.

## Acceptance

- `uv run pytest tests/golden -q` leaves `MATCH (c:Chunk) RETURN count(*)` unchanged.
- Two concurrent writers (a test run and a `cli index`) cannot make a trap fail.
- Traps still pass with a cold graph.
