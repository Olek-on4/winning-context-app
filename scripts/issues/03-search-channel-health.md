# retrieval: report which search channel answered in the envelope

Lane C (Search). Owner: unclaimed.

## Problem

`retrieval/hybrid.py::search` catches every exception per channel and reports `degraded`
only when *both* channels are empty. A dead vector channel therefore looks identical to a
healthy lexical-only index. This is not hypothetical: until commit `409b1ff`,
`graph/chunks.py` never wrote `ch.embedding`, so the vector index held zero rows and every
answer silently came from BM25 alone — with `degraded: false`.

## Evidence

```
$ cd apps/context-service && uv run python -c "from retrieval.hybrid import search; ..."
# before 409b1ff: all results via='bm25', VECTOR index empty
$ ... MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(*)
0
```

The `_chunk()` helper already carries `via`; the answer envelope drops it.

## Change

- `search()` returns channel status alongside the fused list, e.g.
  `{"bm25": "ok"|"error"|"empty", "vector": "ok"|"error"|"empty"}`.
- `retrieval/service.py` puts it in `gaps` when a configured channel failed, and sets
  `degraded: true` when fewer channels answered than the index claims to have.
- Keep the answer text unchanged: a smaller answer with an honest note, never a guess.

## Acceptance

- With vLLM/Ollama stopped, a query returns `degraded: true` and names the vector channel.
- With both channels live, `degraded: false` and no gap line.
- Existing golden traps stay green (`tests/golden/test_traps.py`).
