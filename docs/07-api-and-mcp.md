# 07 — API and MCP surface

The 15-point area: *"how effectively the Context Service can be used by humans, IDEs,
and agentic AI coding assistants, including access through MCP, APIs, or similar."*

## One service layer, two transports

```mermaid
flowchart LR
    subgraph CLIENTS
        A["Claude Code · Cursor · Zed<br/><i>stdio MCP</i>"]
        B["chat / web UI"]
        C["CI job · scripts"]
    end
    A --> MCP["MCP server<br/>4 tools"]
    B --> REST
    C --> REST["FastAPI<br/>/v1/*"]
    MCP --> SVC["<b>ContextService</b><br/>plan → compile → retrieve → assemble"]
    REST --> SVC
    SVC --> NEO[(Neo4j)]
```

The MCP server is a thin adapter over the same `ContextService` the REST API calls.
No logic lives in a transport. This is not tidiness for its own sake: it means MCP
tools are testable without an MCP client, which is the difference between a
demoable integration and one that breaks on stage.

## MCP tool design

MCP is a user interface for an agent, not a REST wrapper. The guidance that shapes
this surface ([sources](research/sources.md#mcp-design)): design top-down from what
the agent is trying to accomplish; keep the tool count small because tool schemas can
consume ~40% of an agent's tokens before it does anything; compute server-side and
return conclusions, not raw rows.

So: **four tools** — three workflow tools, one per CQP intent the demo exercises, plus
the citation reader. Not `get_node`, `list_edges`, `run_cypher`. Six were designed;
three ship plus `resolve_span` — [ADR-0006](adr/0006-scope-of-the-build.md).

| Tool | For the agent's question | Returns |
|---|---|---|
| `context_search` | "what do we know about X?" | ranked claims + citations + status |
| `context_explain_relationship` | "how do A and B connect?" | linked claims, one hop, each with evidence and dates |
| `context_risks` | "what's unsafe here?" | claims of a violation or prohibition + evidence + status |
| `resolve_span` | "show me the bytes behind that citation" | the corpus lines at `path:start-end`, or an error object |

Shared parameters across the three workflow tools: `question`, `as_of`, `status_in`,
`token_budget`, `effort`, `detail`. `resolve_span` takes `path`, plus either
`start`/`end` for lines or `region` as `x,y,w,h` for a picture.
An agent that learns one tool has learned all three. `context_conflicts`,
`context_timeline` and the impact-of-change question exist as CQP intents behind
`POST /v1/query` / `POST /v1/execute` and are promoted to tools only when an agent needs
them.

`context_risks` is the one that closes the loop on the brief's fourth scenario
(*"ensure that generated code does not repeat the same security risks"*). It does not
just report SEC-22; it returns the **prohibition** — the pattern to avoid and the
corpus evidence for avoiding it — in a form an IDE agent can act on before it writes
the handler.

### Tool responses are agent-shaped

Compact, deterministic key order, no decorative prose, token-budgeted
([06](06-retrieval.md#context-budget)). Every response carries `status`,
`confidence` and `citations`, so a downstream agent can decide *for itself* whether
to act — rather than receiving confident text and having to trust it.

## REST surface

```
POST /v1/query              { question, as_of?, status_in?, token_budget?, effort?, detail? }  → answer envelope
POST /v1/plan               { question }                                     → CQP (no execution)
POST /v1/execute            { plan }                                         → answer envelope
GET  /v1/entity/{kind}/{key}                                                 → answer envelope, exact identity
GET  /v1/span?path=&start=&end=                                              → verified bytes for a citation
GET  /v1/span?path=&region=x,y,w,h                                           → the cited rectangle, as PNG
GET  /v1/sources                                                             → indexed roots + chunk counts
GET  /v1/sources/{path}                                                      → one indexed root
GET  /healthz  /readyz  /v1/index/status                                     → ops
GET  /v1/mcp                                                                 → tool specs (name, intent, params)
POST /v1/mcp/{tool}         { params }                                       → { tool, params, result }
```

Designed but **not built** (column 2 of the six-intent scope): `/v1/entity/{kind}/{key}/timeline`,
`/v1/conflicts`, `/v1/gaps`. They need intents and corpus-wide report shapes that
ADR-0006 cut, and inventing a fourth transport surface for them now would be scope, not
polish.

`/v1/mcp/{tool}` runs the same four tools the stdio server registers, over the same
backend, and returns the arguments beside the answer so a reviewer can check both. It is a
demonstration surface, not a second MCP transport: MCP itself stays stdio (ADR-0003), and
nothing in the planner or the resolver knows this route exists. Tool specs are served by
`GET /v1/mcp` so the web console renders real parameters instead of a caption that rots.

The four tool functions live in `apps/context-service/toolcall.py`, imported by both
`api/app.py` and `mcp_server/server.py`. That is a deliberate, temporary third shared
module — flagged as a shortcut in the file — because the alternative was duplicating the
envelope shaping and the tool specs in two adapters that must agree byte for byte.
Consolidating it into `models/` is the post-demo move; it needs the workstream agreement
that module changes require.

`/v1/plan` and `/v1/execute` are split deliberately: it makes the plan inspectable,
lets a human or a test fix a plan the planner got wrong, and turns
"show the judges how the query actually works" into a single `curl`.

The plan response also carries `source` and `detail`, because "parsed" and "understood"
are different claims and only one of them can be checked:

| `source` | `detail` | Meaning |
|---|---|---|
| `deterministic` | the question names an identifier | ADR-0005 kept the keyword plan; the model was never called |
| `deterministic` | model call failed: `<Exception>` | the model is misconfigured or absent — the floor held |
| `deterministic` | model plan carried no typed anchor; discarded | the model answered but recognised nothing |
| `model` | typing anchors only the model resolved | a model produced the anchors this answer uses |

Measured with the planner model actually loaded (`llama3.2`, 2.6 GB): a question that names
nothing produced `source: deterministic` with `detail` *"model plan carried no typed
anchor; discarded"*. The call succeeded — the 3B model simply cannot name an entity it has
never seen, so it returns `ANY` anchors and the plan is discarded by design. Two
consequences worth knowing:

- **Pulling the planner model does not change the answers on this corpus.** It changes the
  `detail` field from *"model call failed"* to *"model plan carried no typed anchor"*. The
  semantic-claim channel (ADR-0010) is what makes an unnamed question answerable, and it
  uses the embedder, not the planner.
- **A cold planner is slower than a query timeout.** The first call after boot loads 2.6 GB;
  `MODEL_TIMEOUT_S` is 30 s for that reason, after which `keep_alive` holds it resident.
  `make models` pulls both and fails loudly rather than leaving a silent downgrade.

Every query route and MCP tool also accepts `effort` (integer 0–4, optional). Omit it and
the planner decides from the question; send it and it wins, clamped to the range. Level 0 is
"the exact graph query and nothing else", 4 is "search the embedded claim statements
widest". An unreadable value is rejected with a 422 rather than guessed at, because a
silently different effort level is a silently different answer
([ADR-0010](adr/0010-semantic-claims-and-effort.md)).

The answer envelope is frozen and does **not** carry this: `plan()` stays a pure CQP
because `answer()` round-trips it through `CQP.model_validate`, which forbids extra
fields. Provenance is `/v1/plan`'s job alone.

### Effort and detail are two different promises

`effort` (0–4) is how hard the service looks. `detail` (`low` · `medium` · `high`) is how
much of what it found comes back. They are separate because an agent may want the widest
search and the shortest reply, or the narrowest search and every byte behind it.

| level | what a finding carries | envelope |
|---|---|---|
| `low` | statement, status, confidence, `valid_from`/`valid_to`, `superseded_by`, **one** citation (`path`, `lines`, `hash`) | answer, claims, conflicts, gaps, degraded — no `evidence` |
| `medium` (REST default) | adds `id`, `subject`, `predicate`, `polarity`, `why_not_valid`, every citation | adds `evidence` passages |
| `high` | adds `extractor`, `extractor_version`, `observed_at`, `modality`, `authority`, and an `excerpt` of the cited lines on each citation | adds the executed `plan` |

A gap never contradicts the level: `low` drops the "passages returned" note along with
the passages, so every note in `gaps` can be checked against the response that carries it.

MCP defaults to `low` and REST to `medium`: an agent pays for every token it reads, while
the web UI renders the whole envelope. The level actually used is echoed as `detail` in
the response, so a caller whose level was unreadable can see it was replaced by `medium`
rather than assume it was honoured. `excerpt` is capped by `DETAIL_EXCERPT_CHARS` and is
charged against `token_budget` like any other text, so `high` truncates rather than
overruns.

The answer envelope has five keys and a sixth layer (at `medium` and above):

| key | what it is |
|---|---|
| `answer` | one line of prose, the statuses that matter |
| `detail` | the level this response was actually built at |
| `claims` | statused, dated, span-verified triples — each with `citations` |
| `conflicts` | claims that disagree with each other |
| `evidence` | **verbatim passages, hash- and line-verified, with `path`, `lines`, `heading`** |
| `gaps` | what was missing, and which channel broke |
| `degraded` | a channel failed; not the same as "nothing matched" |
| `plan` | at `high`: the executed CQP, so a surprising answer is auditable in place |

Corpus text is **never returned bare**. `excerpt` and `evidence[].text` arrive inside
`<untrusted_source path="…">` delimiters, because the same string lands in an agent's context
window and invariant 3 is not optional. The bytes inside the tags are verbatim; only the
guard is added, and the web console strips it for display.

`evidence` exists because most of a corpus never becomes a claim (284 claims from 897
chunks). A passage carries **no status** — it is quoted text, not a verdict
([ADR-0011](adr/0011-evidence-layer.md)). Its count follows `effort` (2/3/5/8 for levels
1–4) and structural noise is rejected by shape, not by filename.

`/v1/gaps` and `/v1/conflicts` are *corpus-wide* endpoints with no question attached.
They are the ones an engineering manager runs, and they are the strongest evidence
that this is a context service rather than a chatbot: *"here are the 14 wiki pages
your repository has outgrown."*

## Security

Two threats matter, and they point in opposite directions.

### 1. The corpus is untrusted input

Everything in `vendor/` is text that will end up inside an agent's context window.
Indirect prompt injection via retrieved content is the dominant agentic-RAG attack
class, and the baseline mitigation is unambiguous: **treat every retrieved chunk as
untrusted user input** ([sources](research/sources.md#prompt-injection)).

- Excerpts are returned inside explicit `<untrusted_source path="…">` delimiters.
- A deterministic scanner flags imperative-to-the-assistant patterns ("ignore
  previous instructions", "you are now…", "system:") in retrieved text and marks the
  span `suspicious: true` rather than silently stripping it — a seeded injection in
  an enterprise repo is itself a finding worth reporting.
- The planner sees **the user's question only**, never retrieved content. Retrieved
  text cannot influence which query runs. This is the structural defence, and it
  comes free from the CQP split in [06](06-retrieval.md).
- Tool outputs never carry executable instructions to the calling agent.

### 2. The service must not leak or mutate

- Neo4j credentials are read-only for the query path; only the ETL user writes.
- Templates are parameterised and read-only; there is no Cypher path from user input
  ([06](06-retrieval.md#the-position-the-model-never-writes-a-query)).
- The corpus contains synthetic secrets by design. The indexer **detects and
  classifies** them as `Risk` nodes but stores a redacted excerpt — the finding is
  "a hardcoded credential exists at this line", never the credential.
- MCP runs over stdio, local, unauthenticated-by-locality for the hackathon. A
  network deployment needs auth and per-tenant scoping; that is
  [Forward View](09-evaluation.md#forward-view), and it is named rather than assumed.

## IDE integration

```jsonc
// .mcp.json — same block as an OMP session's ~/.config/mcp/mcp.json entry
{
  "mcpServers": {
    "etyt-context": {
      // --directory is not optional: `-m cli` imports from the app directory, and a
      // client spawns the command from its own cwd.
      "command": "uv",
      "args": ["--directory", "<repo>/apps/context-service", "run", "python", "-m", "cli", "mcp"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "etyt-context"
      }
    }
  }
}
```

Verified end to end from a foreign cwd with the credentials above: the server starts,
lists `context_search`, `context_explain_relationship`, `context_risks` and
`resolve_span`, and answers with cited claims. It needs the Neo4j container from
`infra/neo4j/compose.yaml` running; with the store down it still starts and reports
`degraded: true` with the failed channel named, rather than hanging or guessing.

The demo that makes the 15 points real: in the IDE, ask *"add a cache to the stock
read path"*. Without the service, an agent reads `wiki/inventory-service.md`, finds
Redis, and reintroduces `REDIS_URL` — reversing a decision the team made in June.
With `context_search`, it gets ADR-003 with a `DEPRECATED` label on the wiki claim
and declines. **That is the product**, in one interaction, and it is a scenario the
corpus was built to contain.
