# Ety&T — Etymology & Translation

Built for the AT&T Context Service hackathon. **Ety&T** is an evidence-backed, time-aware
Context Service over the [Northstar Equipment](https://github.com/arkik7/att-hackathon-task)
corpus (twelve apps, docs, wiki, meeting notes, incidents, API specs, diagrams).

The corpus lives in `vendor/att-hackathon-task` as a git submodule and is the only
source of input data. Everything in this repository is our own code.

## The idea in one paragraph

In this corpus the *most relevant* passage is usually the *stale* one — a wiki page
documents a Redis cache that an ADR removed four months later, and a vector search
ranks the wiki page first. So the unit of knowledge here is not a chunk and not a
triple: it is a **claim**, carrying provenance to an exact line range, a validity
interval, a status (`VALID` · `DEPRECATED` · `PLANNED` · `PROPOSED` · `DISPUTED`) and
a confidence. Entities and relationships are derived from claims by a deterministic
resolver, never asserted by an extractor. Questions are answered by a validated query
plan compiled to parameterised Cypher — the model never writes a query.

## Status

**The spine runs.** Four pipelines, six intents, three MCP tools, seven corpus traps
answered end to end with citations; `make check` is the gate. Design record:
**[docs/README.md](docs/README.md)**.

- [docs/02-architecture.md](docs/02-architecture.md) — the system end to end
- [docs/03-ontology.md](docs/03-ontology.md) — how knowledge is represented
- [docs/04-temporal-model.md](docs/04-temporal-model.md) — how validity is decided
- [docs/08-delivery-plan.md](docs/08-delivery-plan.md) — four developers, five hours
- [docs/10-workstreams.md](docs/10-workstreams.md) — who builds what
- [docs/local-model.md](docs/local-model.md) — running the embedding model on the GPU
- [docs/plan-review.html](docs/plan-review.html) — visual review of the plan: pillars, mechanics, findings
- [docs/adr/](docs/adr/) — decisions and their rejected alternatives

## Who builds what

Four lanes, one owner each, four frozen contracts between them
([detail](docs/10-workstreams.md)):

| Lane | Owns | Hands over |
|---|---|---|
| **Extraction** | `ingest/` | `claims.jsonl` passing the schema, span and ontology gates |
| **Core** | `graph/`, `infra/neo4j/` | a resolved graph where status and time are decided |
| **Search** | `retrieval/` | question → validated CQP → parameterised Cypher → answer envelope |
| **MCP / API** | `api/`, `mcp/`, `tests/golden/` | REST + three MCP tools, and the seven-trap golden set |

Only two waits exist (extraction→core, core→search) and both consume a file, not a
running service.

## Use it

```sh
make docker-up          # neo4j + ollama + app, all healthy
make docker-demo        # pull model, extract, load, index -- then it prints a curl
make test               # whole suite, no containers needed except the golden traps
make e2e                # proves the containerised stack answers REST and MCP
```

Ask it things over REST:

```sh
curl -s localhost:8000/v1/query -H 'content-type: application/json' \
  -d '{"question":"Does inventory-service still use a Redis cache?"}'
```

Every claim comes back with `status`, an interval and citations as
`{path, lines, hash}`. The text behind a citation is served by
`GET /v1/span?path=…&start=…&end=…`, never stored twice.

### Add your own data

A "source" is any directory. Point the extractor at it and it is indexed and
discoverable immediately:

```sh
cd apps/context-service
uv run python -m cli extract --source /path/to/your/repo --source ../../vendor/att-hackathon-task
uv run python -m cli load /path/to/claims.jsonl        # EXTRACTED_PATH controls the file
uv run python -m cli index --source /path/to/your/repo --source ../../vendor/att-hackathon-task
```

The **server** must be told the same roots, or citations from the new tree fail
verification at query time. `SOURCES` is colon-separated and applies to `serve` and `mcp`:

```sh
SOURCES=/path/to/your/repo:$PWD/../../vendor/att-hackathon-task \
  uv run python -m cli serve
```

Worked example, measured: a three-file directory (`conf/ports.json`, `schema/003-invoices.sql`,
`notes/billing.md`, git-initialised) added as a second root produced 28 claims —
`billing-api LISTENS_ON 9100`, `invoices NOT HAS_COLUMN state` / `ASSERTS invoice_status` —
and both answered over HTTP with citations that resolve through `/v1/span`.

What happens automatically: every text file is chunked and embedded for search; `.sql`
`ALTER TABLE` statements become `HAS_COLUMN` claims (renames emit a negation);
`compose.yaml`, `package.json` and `CODEOWNERS` become `DEFINED_IN` / `DEPENDS_ON` /
`OWNS`; markdown `Date:`/`Status:`/`Owner:` headers become document facts. Claims carry
a pointer and a file hash, so a citation can always be re-read from the tree.

A new *data type* is one class plus `register()` — see
`apps/context-service/ingest/registry.py`; nothing else changes, and
`tests/test_agnostic.py` proves it on a directory that shares no layout with the corpus.

### Test that it finds things

```sh
uv run pytest tests/golden -v        # seven traps: answer + status + citation
uv run pytest tests/test_vectors.py  # every chunk has a vector, paraphrase retrieves
make rehearse                        # cold start: wipe, rebuild, serve, seven steps
make e2e                             # same, through the container stack
```

The honest test is the negative one: ask "can I join employees to customers by email?"
It must answer **no** and show `SIMILAR_NAME_TO`, not an invented join.

## Layout

```
.
├── apps/context-service/     our implementation (Python 3.12)
├── docs/                     design, ADRs, research
├── data/fixtures/            small, reviewed, committed
├── tests/golden/             the seven corpus trap cases
├── vendor/att-hackathon-task corpus submodule, read-only
└── LICENSE                   MPL-2.0
```

## Clone

The corpus is required for every task that touches data:

```sh
git clone --recurse-submodules <repo-url>
# existing checkout:
git submodule update --init --recursive
```

Refresh the corpus to the pinned commit after a pull:

```sh
git submodule update --recursive
```

## Run it

Two paths, one API at `http://127.0.0.1:8000`.

**Host** — Python 3.12 + `uv`, Neo4j in Docker, Ollama on the host:

```sh
make up      # start neo4j
make demo    # up extract load index, then print the query to run
make serve   # REST on :8000
```

**Containers** — Neo4j, Ollama and the service all in Docker, corpus mounted read-only:

```sh
make docker-up     # build + start etyt-neo4j, etyt-ollama, etyt-app
make docker-demo   # pull the model, then the same pipeline inside etyt-app
```

| Container | Role |
|---|---|
| `etyt-neo4j` | `neo4j:5-community`; browser on `http://127.0.0.1:7474`, auth `neo4j` / `etyt-context` |
| `etyt-ollama` | `ollama/ollama` on `http://127.0.0.1:11435` (11434 belongs to a host-side Ollama) |
| `etyt-app` | the Context Service; REST + MCP; `http://127.0.0.1:8000` |

The model lives in a volume, so it is pulled once — `make docker-demo` does it, and
`make docker-index` re-indexes inside `etyt-app` after that. Inference is CPU-only on this
host: there is no nvidia runtime, so the GPU block in the compose file stays commented out.
Full rehearsal script: [docs/demo.md](docs/demo.md).

## Corpus facts

- Source of truth: `vendor/att-hackathon-task` (MIT licensed, fictional organization),
  pinned at `612cc0b`. 373 tracked files, 3.3 MB.
- Main material: TypeScript/Python/Java apps, `docs/`, `wiki/`, `meeting-notes/`,
  `issues/`, `incidents/`, `releases/`, `api-specs/`, `diagrams/`.
- It contains deliberate contradictions, superseded documents and false joins.
  The catalogue of them is [docs/01-corpus-survey.md](docs/01-corpus-survey.md) and it
  doubles as our test suite.
- Running the upstream apps is optional; source inspection is sufficient. Derived
  stores (parsed corpus, embeddings, indexes) must not be committed.

## Contributing

Read [AGENTS.md](AGENTS.md) first. It is binding for humans and agents alike.

## License

MPL-2.0. See `LICENSE`. The corpus submodule keeps its own MIT license.
