# winning-context-app

Solution for the AT&T Context Service hackathon. An evidence-backed, time-aware
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

**Design frozen, not yet implemented.** Start at **[docs/README.md](docs/README.md)**.

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
