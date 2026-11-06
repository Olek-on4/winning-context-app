# graph: drop chunks that no longer exist in the corpus on re-index

Lane B (Core). Owner: unclaimed.

## Problem

`graph/chunks.py::index` only `MERGE`s. A file that shrinks, is renamed, or is deleted leaves
its old `Chunk` rows in the graph with the old text, so retrieval can return content that is
no longer in the repository — exactly the drift the pointer-only design exists to prevent.
This got worse in `409b1ff`: chunk ids changed scheme, and the 685 pre-existing rows stayed
behind until the graph was wiped by hand.

## Evidence

```
$ cd apps/context-service && uv run python - <<'PY'
# index, delete a corpus file, index again, count chunks whose Source hash is stale
PY
```

Reproduce by removing any file from `vendor/att-hackathon-task`, re-running `cli index`, and
querying `MATCH (ch:Chunk)-[:IN]->(s:Source) WHERE s.content_hash <> <current>`. Nothing
removes them today.

## Change

- `index()` collects the set of `Source` paths (and hashes) it wrote for the roots it was
  given, then, in the same run, deletes `Chunk` nodes whose `Source.path` is under those
  roots but whose `(id, hash)` pair was not written this pass.
- Scope the delete to the roots passed on the command line: `--source` must not wipe chunks
  belonging to another root.
- Keep it one statement per root, same session, no new module.

## Acceptance

- Index a temp corpus, delete one file, re-index: chunk count drops by that file's windows
  and a fulltext query for its text returns nothing.
- Re-indexing an unchanged corpus is a no-op (same chunk count, same ids).
