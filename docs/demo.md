# Demo — seven minutes, and how to get the graph back

Rehearsed on the demo machine, not on a laptop that works. The graph is **reproducible**,
so there is no snapshot to carry: the corpus is pinned, the fixtures are committed, and
the deterministic claims are recomputed from migrations and `config/ports.json`.

## Bring-up (2 minutes, before the room fills)

```sh
docker compose -f infra/neo4j/compose.yaml up -d          # neo4j:5-community
cd apps/context-service
uv run python -m cli extract                              # 17 deterministic claims
uv run python -m cli load ../../data/fixtures/claims-sample.jsonl
uv run python -m cli index                                # 85 chunks, BM25 (+vectors if Ollama is up)
uv run python -m cli serve                                # :8000
```

`cli index` prints `{"embedded": false}` when no model is present. That is supported:
BM25 answers on its own, and the answer envelope says so.

## The seven minutes

1. **The problem, from the corpus** (45 s). Open `wiki/inventory-service.md:5` and
   `docs/adr/003-stock-cache.md:6` side by side. "Both are in the repo. One is wrong.
   Nothing in the repository says which."
2. **Naive retrieval fails** (30 s). Vector search for "stock cache" ranks the wiki page
   first, confidently.
3. **The service answers** (90 s).
   ```sh
   curl -s localhost:8000/v1/query -H 'content-type: application/json' \
     -d '{"question":"Does inventory-service still use a Redis cache?"}'
   ```
   Point at: `VALID … sqlite`, `VALID … NOT READS_FROM redis`, and the
   `DEPRECATED … redis` row whose `valid_to` is `2026-06-04`.
4. **The IDE loop** (90 s). In Claude Code, `.mcp.json` already points at
   `uv run python -m cli mcp`. Ask "add a cache to the stock read path" — the agent calls
   `context_search` and declines, citing ADR-003.
5. **The ontology in one slide** (60 s). Three planes, four layers, why claims and not
   triples. `docs/plan-review.html` has the pictures.
6. **Time travel** (45 s). Same question with `"as_of":"2026-03-01"` — "yes, Redis".
   Same graph, earlier clock.
7. **Limitations, said before they are found** (60 s) — next section.

## What to say out loud in the last minute

- **Source authority is a hand-tuned table**, defensible for this corpus and unvalidated
  for any other. It should be learned from outcomes.
- **The resolver handles supersession, not revision.** "X now does Y except on weekends"
  degrades to `DISPUTED` — safe, not helpful.
- **No embedded model on most laptops**, so retrieval is lexical by default. Vectors are a
  config change, not a redesign.
- **Code and diagram pipelines are not built** (`ADR-0006`): T1 resolves from prose,
  paths and migrations, which is where the corpus puts its contradictions.
- **`ncs verify`, `/v1/gaps`, auth and multi-tenancy are forward view.** Column 3 of the
  scope line is a slide, not a branch.

## Reproducibility

| Piece | Pinned by |
|---|---|
| Corpus | submodule commit `612cc0b` |
| Claims | `data/fixtures/claims-sample.jsonl` (reviewed) + `cli extract` (deterministic) |
| Schema | `apps/context-service/graph/schema.cypher`, applied on every load |
| Proof | `uv run pytest tests/golden -v` — 7 rows, answer + status + citation |

To reset for a clean run: `MATCH (n) DETACH DELETE n` then the two `cli` commands above.
