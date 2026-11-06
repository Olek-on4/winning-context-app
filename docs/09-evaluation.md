# 09 — Evaluation, limitations, forward view

## How we know it works

### The golden set is the trap catalogue

Seven questions, seven known-correct answers, derived by reading the corpus
([01](01-corpus-survey.md#the-trap-catalogue)). Each asserts three things: the right
answer, the right *status labels*, and the right citations.

| # | Question | Must answer | Must label | Must cite |
|---|---|---|---|---|
| G1 | Does inventory-service use a Redis cache? | No, since 2026-06-04 | wiki + Jan diagram `DEPRECATED` | `adr/003:6`, `releases/2026-06-v1.3.md` |
| G2 | What fields does the users table have? | `id, display_name, email, account_status, customer_tier` | wiki `status` claim `DEPRECATED` | `migrations/002-account-tiers.sql:1-2` |
| G3 | Should I generate a client from accounts-v1? | No, superseded | `DEPRECATED` by path | `api-specs/history/accounts-v1.md` |
| G4 | Can I join employees to customers by email? | No — explicit mapping only | `SIMILAR_NAME_TO`, **not** identity | `design/people-account-link.md:6`, `wiki/accounts-http.md:9` |
| G5 | Is `PaymentService` part of the payment flow? | No — the archive one is a voucher calculator | out of workspace | `archive/conference-registration/README.md:5` |
| G6 | Do we have SSO between People and Accounts? | No — proposed only | `PROPOSED`, never `VALID` | `adr/004:3-4` |
| G7 | Are there authorisation risks in order lookup? | A suspected one, unverified | `DISPUTED` + CWE-639 | `issues/SEC-22.md:3-7` |

G4 and G5 are **negative** tests: the service must *refuse* to connect things. Those
are the ones a plausible-sounding system fails, and they are worth more than the
positives as evidence of trustworthiness.

```sh
pytest tests/golden -v    # 7 rows: answer ✓/✗ · status ✓/✗ · citations ✓/✗
```

Three separate assertions per question, because a right answer with wrong citations
is a lucky guess, and a system that can guess luckily will eventually guess unluckily.

### Component-level checks

| Layer | Metric | Target | Method |
|---|---|---|---|
| Extraction | span-gate pass rate | ≥ 85% of LLM claims | counted during ingest |
| Extraction | deterministic claim precision | 100% | 30-claim manual audit |
| Retrieval | recall@10 on golden anchors | ≥ 0.9 | fixed query set |
| Resolution | status accuracy on the 7 traps | 7/7 | golden set |
| Latency | p95 `context_search`, warm | < 800 ms | timed in the harness |
| MCP | tool-schema token cost | < 2 000 tokens for all 6 | measured once |

RAGAS-style faithfulness/context-precision scoring
([sources](research/sources.md#rag-evaluation)) is the right instrument at scale but
needs an LLM judge per sample, which we cannot afford in five hours on local models.
Documented as forward work; the golden set is the five-hour substitute and it is
sharper for this corpus because the answers are *known*, not judged.

### Observability

Every request emits an OpenTelemetry trace with spans for `plan`, `validate`,
`anchor`, `retrieve`, `traverse`, `assemble`, following the `gen_ai.*` semantic
conventions ([sources](research/sources.md#observability)). The CQP is attached to the
root span. When an answer is wrong, the plan that produced it is in the trace — which
is the difference between debugging and guessing.

## Limitations

Stated before a judge finds them. Every one is real.

**Diagram extraction is the weakest link.** The best measured VLM reaches ~70% on
software-architecture-diagram understanding, and frontier models fall below 60% on
structured engineering diagrams ([sources](research/sources.md#vlm-diagrams)). Our
local VLM is worse. We cap diagram authority at 0.40, require corroboration before
promotion, and for these six images we human-verify the extraction and commit it as a
fixture. **At scale that manual step does not exist**, and diagram-only knowledge
would remain `DISPUTED` more often than is useful. This is the gap between our demo
and our architecture, and it is the honest one.

**Source authority is a hand-tuned prior.** The table in
[03](03-ontology.md#source-authority) encodes our judgement that a migration outranks
a wiki page. It is defensible for this corpus and unvalidated for any other. It
should be learned from outcomes, not asserted.

**The resolver handles supersession, not revision.** "Remove X" is handled. "X now
does Y instead of Z, except on weekends" is not. Partial, conditional and scoped
revisions degrade to `DISPUTED` — safe, but unhelpful.

**LLM extraction recall is unmeasured.** The span gate gives us high *precision*. We
have no way to know how many true claims the local model simply failed to emit, and
with a 7–8B model the answer is probably "many". A Context Service that silently
omits knowledge is a quieter failure than one that invents it, and we have not
measured it.

**No cross-repository story.** Everything assumes one checkout at one commit. Real
enterprise context spans hundreds of repos with independent histories, which changes
entity resolution from "scope by workspace" to a genuinely hard problem.

**Security detection is pattern-based.** SAST tools are documented as missing
confirmed vulnerability classes even in curated configurations
([sources](research/sources.md#semgrep)). We flag shapes, corroborate against issue
records, and report confidence. We do not claim coverage.

**Five hours is five hours.** Column 3 of the
[scope line](08-delivery-plan.md#scope-line) is designed, not built. Where this
document describes behaviour, check it against what the demo actually runs.

## Forward view

The 10-point area: scaling, maintenance, real workflows, staying accurate and
trustworthy over time.

### Scaling

The ingest path is already the right shape — per-file independent, content-hash
addressed, parallel by file, incremental by blob. 100k files is a scheduling problem.
What breaks first, in order:

1. **The temporal resolver is quadratic per subject.** It compares every claim about
   a subject-predicate against every other. Partition by subject and process groups
   independently; the comparison never needs to be global.
2. **Community detection is a full-graph batch.** Incremental Leiden is unsolved in
   practice; move to nightly rebuilds with a stable-ID mapping so topic references
   survive.
3. **Local-model extraction throughput**, ~1–3 files/s. Batch inference on a GPU, or
   reserve the model for the narrative pipeline only — which is already where it
   earns its cost.
4. **Neo4j single-instance writes.** Read replicas first; sharding by repository is
   natural because the workspace boundary already partitions the graph.

The hierarchical L3 layer is what keeps *query* cost flat as the corpus grows, since
traversal is scoped to the communities an anchor belongs to. That is the piece we
cut for time and the first one to build next.

### Keeping it accurate

- **`ncs verify` as a nightly job.** Every claim is pinned to
  `(path, lines, content_hash)`. Re-check them and report drift. The service can
  prove whether it still matches the repository — the one guarantee a staleness
  detector must be able to make about itself.
- **Ingest on merge.** A post-merge hook runs `ncs ingest --since` on changed blobs.
  Context lags code by one CI run, not one quarter.
- **Contradiction as a PR check.** If a PR introduces a claim that contradicts an
  `Accepted` ADR, fail the check and cite it. This is the point where the Context
  Service stops being a lookup tool and starts preventing the problem it was built to
  describe — the Redis case would have been blocked at review rather than discovered
  four months later.
- **Decay.** A claim with no corroboration and no re-observation for N months has its
  confidence decayed rather than its status changed. Staleness is a gradient.
- **Human adjudication loop.** `DISPUTED` claims are a work queue, and a human
  decision becomes a new claim at authority 1.0. The graph gets more trustworthy
  through use, which is the only maintenance model that survives contact with a real
  organisation.

### Real developer workflows

The MCP server is the integration ([07](07-api-and-mcp.md)) and the IDE is the first
surface, but the higher-leverage placements are the ones where context is *pushed*:
the PR check above; a `/context` command in the team chat answering from the same
graph; the `/v1/gaps` report as a quarterly documentation-debt list. The service
earns its keep when nobody has to remember to ask it.

### Trustworthiness over time

The architecture's one non-negotiable property is that **every claim is reproducibly
checkable against a byte range of a file at a known hash**. Models change,
extractors improve, authority priors get retuned — and every historical answer
remains auditable, because the evidence is a pointer into the repository rather than
a model's recollection of it. That is the property we would defend if we had to
rebuild everything else.
