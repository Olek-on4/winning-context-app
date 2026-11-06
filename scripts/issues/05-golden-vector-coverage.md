# golden: assert the vector channel contributes, not just that an answer arrives

Lane D (MCP/API + golden set). Owner: unclaimed.

## Problem

The seven traps assert answer, status and citation. None of them can tell a hybrid answer
from a lexical one, so the dead vector path shipped, passed `make check`, and passed
`scripts/rehearse.py` — which only prints `embedded=True` from `cli index`, i.e. from the
embedding *probe*, not from stored vectors.

## Evidence

`409b1ff` fixed `graph/chunks.py`; before it, `MATCH (c:Chunk) WHERE c.embedding IS NOT NULL`
returned 0 of 1119 while `cli index` printed `{"chunks": 1119, "embedded": true}`.

`48ceabc` then made the golden fixture build its own index, because the suite previously
depended on a prior `cli index` run and failed with an empty retrieval layer.

## Change

- Add one integration test in `tests/golden/` that indexes with `embed=_embed`, then asserts
  a paraphrase query whose exact tokens are absent from the winning chunk still ranks it in
  the top 3 with `via` containing `vector`. Skip when the model is unreachable, exactly as
  the Neo4j tests skip.
- Assert the invariant directly too:
  `MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(*)` equals total chunk count.

## Acceptance

- With Ollama up: the paraphrase test passes and would fail if `ch.embedding` were dropped
  from the upsert.
- With Ollama down: both tests skip, suite still green.
