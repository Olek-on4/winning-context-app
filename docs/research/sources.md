# Research sources

Literature review, 2026-11-06, conducted before the architecture was fixed. Each
entry records **what we took** and, where relevant, **what we rejected** — a source
that only confirms a decision we had already made is not evidence.

---

## <a id="bitemporal"></a>Bi-temporal knowledge graphs

- Zep — [*What Is a Temporal Knowledge Graph?*](https://www.getzep.com/ai-agents/temporal-knowledge-graph/)
- [*Temporal Knowledge Graphs: What They Are & Why AI Memory Needs Them*](https://www.cognee.ai/temporal-knowledge-graph) (Cognee)
- [*Zep: A Temporal Knowledge Graph Architecture for Agent Memory*](https://signals.aktagon.com/articles/2026/07/zep-a-temporal-knowledge-graph-architecture-for-agent-memory/)
- [*Temporal Validity in Retrieval Memory: Eliminating Stale-Fact Errors for AI Agents over Evolving Knowledge*](https://arxiv.org/pdf/2606.26511)
- [*post-graph-rag: A PostgreSQL-Native Bi-Temporal Graph RAG Engine with Temporal Grounding at Synthesis*](https://arxiv.org/pdf/2608.24921)

**Taken.** The four-timestamp edge model — `valid_from` / `valid_to` (world) and
`observed_at` / `recorded_at` (system) — and the invalidation discipline: *a
contradicted edge is stamped invalid, never deleted*. Graphiti (the open-source
library behind Zep) reports up to 18.5% accuracy improvement with ~90% latency
reduction on LongMemEval using this model plus hybrid retrieval. `post-graph-rag`
independently validates that the model works on a conventional relational/graph
store rather than needing a specialist engine, and contributes *temporal grounding at
synthesis* — applying temporal constraints when composing the answer, not only when
retrieving. Both are in [04](../04-temporal-model.md).

**Not taken.** Graphiti itself. It is built around conversational "episodes" with
LLM-driven entity extraction per episode, which is the wrong ingestion shape for a
static repository and would have cost us the deterministic extraction that this
corpus rewards. We took the data model and left the pipeline.

---

## <a id="lazygraphrag"></a>Graph RAG cost and quality

- Microsoft Research — [*LazyGraphRAG: Setting a new standard for quality and cost*](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- [*When Is Graph Structure Worth Its Cost? The Case for Structure Pricing in RAG*](https://arxiv.org/pdf/2609.18099)
- [*LiteRAG: Cost-Efficient Graph-Based Retrieval-Augmented Generation*](https://arxiv.org/pdf/2609.10239)
- [*E²GraphRAG: Streamlining Graph-based RAG for High Efficiency and Effectiveness*](https://arxiv.org/pdf/2505.24226)
- [*GraphRAG vs Vector RAG: The 1,000x Index Bill Is the Small One*](https://www.beri.net/article/graphrag-vs-vector-rag-indexing-query-cost-lightrag-lazygraphrag-2026)

**Taken.** The decisive numbers: LazyGraphRAG's indexing cost is *identical to vector
RAG* and 0.1% of full GraphRAG, because it builds its concept graph from NLP
noun-phrase extraction and co-occurrence plus graph statistics for hierarchical
community structure — **no LLM at index time**. At query time it spends a bounded
"relevance test budget" (tested at 100/500/1500) on best-first chunk ranking with
breadth-first relevance assessment and iterative deepening, matching GraphRAG global
search at ~4% of its query cost. The insight that justifies it: most pre-computed
community summaries are never queried.

This is the direct basis for our L3 layer being LLM-free
([02](../02-architecture.md#the-four-layers-of-the-index)). With local models and
five hours, pre-summarising communities was never affordable; the research says it
would also have been waste.

---

## <a id="hipporag"></a>Graph-structured retrieval

- [*From RAG to Memory: Non-Parametric Continual Learning for LLMs* (HippoRAG 2)](https://arxiv.org/html/2502.14802v2)

HippoRAG 2 uses Personalized PageRank over a KG with deeper passage integration,
beating the strongest dense retriever by 5.0 and 13.9 points Recall@5 on MuSiQue and
2Wiki, and ~7 points F1 on associative tasks.

**Noted, not adopted.** PPR is the right tool when the query is an unstructured
multi-hop question over an entity graph. Our queries arrive as typed CQP intents with
explicit anchors and predicates, so traversal is directed rather than diffused. PPR
is the natural upgrade if we later add an open-ended "explore around here" intent.

---

## <a id="hybrid-retrieval"></a>Hybrid retrieval and reranking

- Anthropic — [*Enhancing RAG with contextual retrieval*](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide)
- [*From BM25 to Corrective RAG: Benchmarking Retrieval Strategies for Text-and-Table Documents*](https://arxiv.org/html/2604.01733v1)
- [*Hybrid Retrieval: Comparing Rank Fusion and Projection Fusion with Diversity Reranking*](https://arxiv.org/pdf/2604.13728)

**Taken.** Hybrid BM25 + dense with Reciprocal Rank Fusion is the documented minimum
viable baseline, worth 15–30% recall over single-method pipelines; RRF needs no score
normalisation (k = 60 default), which is what makes fusing a Lucene score with a
cosine distance tractable. Hybrid RRF plus cross-encoder reranking dominates all
measured methods, and contextual retrieval at index time (prepending document/heading
context before embedding) adds a consistent gain for a one-time cost. The published
recipe — retrieve ~150, rerank to ~20 — is scaled to 50→10 for our corpus size.
All of this is [06](../06-retrieval.md#retrieval-pipeline).

---

## <a id="chunking"></a>Chunking

- [*RAG Chunking Strategies: The 2026 Benchmark Guide*](https://www.premai.io/blog/rag-chunking-strategies-the-2026-benchmark-guide/)
- [*Reconstructing Context: Evaluating Advanced Chunking Strategies for RAG*](https://arxiv.org/pdf/2504.19754)
- [*Adaptive Chunking: Optimizing Chunking-Method Selection for RAG*](https://arxiv.org/pdf/2603.25333)

**Taken — against our instincts.** Recursive fixed-size splitting at ~512 tokens beat
semantic chunking on end-to-end accuracy (69% vs 54%) in Vecta's February 2026
benchmark, even though semantic chunking won on raw recall (91.9% in Chroma's
evaluation). FloTorch found semantic chunking produced 43-token fragments averaging
54% accuracy. The stated rule — start at 400–600 tokens with reranking, upgrade only
after measuring a gap — is what we follow. Structure-aware splitting *is* required for
code, where fixed-width splitting severs signatures from bodies.

**Not taken.** Late chunking (BEIR gains of ~2–6 nDCG@10, correlated with document
length) and ColBERT-style late interaction. Both are real wins; neither fits five
hours, and our documents are short.

---

## <a id="text2cypher"></a>Natural language to graph query

- [*Extending Confidence-Based Text2Cypher with Grammar and Schema Aware Filtering*](https://arxiv.org/abs/2605.10318v1)
- [*Enhancing Text2Cypher with Schema Filtering*](https://arxiv.org/pdf/2505.05118)
- [*LAST-CQ: What Drives Recovery in Agentic Text-to-Cypher?*](https://arxiv.org/pdf/2609.12746)
- [*PIPE-Cypher: Automatic Enterprise Benchmark Generation for Text-to-Cypher Systems*](https://arxiv.org/html/2606.08481)
- Neo4j — [*Improving Text2Cypher with Test-Time Strategies*](https://neo4j.com/nodes/agenda/improving-text2cypher-with-test-time-strategies/)

**Read, and deliberately inverted.** Every paper here describes the same failure —
generated queries fail on syntax errors and schema mismatch — and proposes another
layer of mitigation: grammar-based filtering, schema-aware filtering, confidence
decoding, execution validation, self-refinement, deterministic Cypher governance, a
calibrated LLM judge.

Our reading is that the mitigation stack is evidence against the approach. All of it
exists to constrain an output space that did not need to be unbounded. Hence the CQP:
the model fills a validated JSON form, a pure compiler emits the Cypher
([06](../06-retrieval.md#the-position-the-model-never-writes-a-query)). We give up
expressiveness and get a query layer that cannot emit a syntax error and is unit-
testable without a model — which, under a five-hour budget, is worth more.

---

## <a id="ontology-guided-extraction"></a>Ontology-guided extraction and validation

- [*OntoLogX: Ontology-Guided Knowledge Graph Extraction from Cybersecurity Logs with LLMs*](https://arxiv.org/html/2510.01409v1)
- [*OntoKG: Ontology-Oriented Knowledge Graph Construction with Intrinsic-Relational Routing*](https://arxiv.org/pdf/2604.02618)
- [*An Ontology-Guided, Deduplication-Aware Extraction Layer for KG Construction from Heterogeneous Documents*](https://arxiv.org/html/2607.28662)
- [*PolicyKG: An Agentic LLM Pipeline for Translating Institutional Policies into SHACL Knowledge Graphs*](https://arxiv.org/pdf/2608.09028)

**Taken.** Constrain the LLM at generation with a structured-output schema rather
than correcting afterwards; validate with declarative constraints on types,
cardinality and relationship patterns; and — the key one — require **source-span
grounding for each candidate class or relation**. Our three gates
([03](../03-ontology.md#storage-indexing-and-validation-in-neo4j)) are this
recommendation implemented with pydantic and Ollama's `format` parameter instead of
OWL/SHACL, which we judged too heavy for the schedule. Ontological constraints during
extraction are reported to reduce hallucination directly.

---

## <a id="entity-resolution"></a>Entity resolution

- [*How does entity resolution work for knowledge graph deduplication, and what actually works in 2026?*](https://indexical.dev/knowledge/how_does_entity_resolution_work_for_knowledge_graph_deduplication_and_what_actually_works_in_2026.php)
- [*Beyond Scale and Generation: Understanding Language Model-based Entity Matching*](https://arxiv.org/pdf/2607.24688)
- [*Less is More: Denoising Knowledge Graphs For Retrieval Augmented Generation*](https://arxiv.org/pdf/2510.14271)

**Taken.** The 2026 consensus cascade: deterministic rules on exact identifiers for
the extremes, a trained scorer for the bulk, LLM adjudication only for the contested
middle — and the reported correction that organisations which replaced rules entirely
with LLMs in 2024–25 reverted on cost and inconsistency.

**Pushed further.** The corpus plants shared emails and duplicate class names
explicitly flagged as non-joins ([01 — T4/T5](../01-corpus-survey.md)), so we truncate
the cascade: declared identifiers merge, resemblance becomes a `DISPUTED`
`SIMILAR_NAME_TO` edge, and an LLM may only *propose* a merge as a `HYPOTHESIS`
claim. "Less is More" supports the direction: denoising a KG improves downstream RAG.

---

## <a id="prov-o"></a>Provenance modelling

- W3C — [*PROV-DM: The PROV Data Model*](https://www.w3.org/TR/prov-dm/)
- [*Full Traceability and Provenance for Knowledge Graphs*](https://www.utwente.nl/en/eemcs/fois2024/resources/papers/dibowski-full-traceability-and-provenance-for-knowledge-graphs.pdf)
- [*OntoKG-EQ: A provenance-grounded, competency-question-governed knowledge graph for auditable analyst querying*](https://arxiv.org/pdf/2609.08869)

**Taken.** The `Entity` / `Activity` / `Agent` separation and `wasDerivedFrom` /
`wasGeneratedBy` chains, as the *shape* of our three planes; and OntoKG-EQ's
**per-result evidence bundles** — provenance attached to the individual answer, not
to the dataset. We do not emit RDF: the vocabulary would cost more than it returns
here, but the auditability property is the entire point of
[03](../03-ontology.md#three-planes).

---

## <a id="code-extraction"></a>Code structure extraction

- [*Codebase-Memory: Tree-Sitter-Based Knowledge Graphs for LLM Code Exploration via MCP*](https://www.researchgate.net/publication/403308415_Codebase-Memory_Tree-Sitter-Based_Knowledge_Graphs_for_LLM_Code_Exploration_via_MCP)
- [*RANGER: Repository-Level Agent for Graph-Enhanced Retrieval*](https://arxiv.org/pdf/2509.25257)
- [infigraph](https://github.com/intuit/infigraph) · [CodeGraphContext](https://codegraphcontext.github.io/)
- [*RFC 001 — Remove SCIP Dependency and Implement Tree-sitter Based File-Incremental Indexing*](https://github.com/orgs/sheeptechnologies/discussions/4)

**Taken.** tree-sitter as the single multi-language parser — Codebase-Memory reports
10× fewer tokens and 2.1× fewer tool calls than a file-exploration agent across 31
repositories, which is the same argument we make for a context service generally.
The January 2026 RFC's reasoning for dropping SCIP is ours too: SCIP-based indexing
requires full graph reconstruction on every update, where tree-sitter supports
file-incremental indexing. With TS, Python *and* Java in this corpus, per-language
SCIP indexers were never affordable.

---

## <a id="vlm-diagrams"></a>Diagram understanding

- [*Benchmarking and Evaluating VLMs for Software Architecture Diagram Understanding* (SADU)](https://arxiv.org/abs/2604.04009)
- [*Knossos and Ariadne: Benchmarking and Learning Complete Diagram Topology Extraction with VLMs*](https://www.researchgate.net/publication/415267471_Knossos_and_Ariadne_Benchmarking_and_Learning_Complete_Diagram_Topology_Extraction_with_Vision-Language_Models)
- [*Enginuity: A Dataset and Benchmark for Vision-Language Understanding of Engineering Diagrams*](https://arxiv.org/html/2606.03410v1)

**Taken — as a constraint, not a capability.** SADU: 154 curated diagrams, 2,431 QA
tasks, 11 frontier VLMs; the best (`gemini-3-flash-preview`) reaches ~70% accuracy
and `gpt-4o-mini` ~18%, with identified weaknesses in *diagram reasoning and visual
relation grounding*. Enginuity: frontier VLMs below 60% on structured engineering
diagrams. Ariadne contributes the method we use — decompose topology extraction into
**node inventory** then **source-conditioned edge prediction** rather than asking for
the whole graph at once.

These numbers are why diagram authority is capped at 0.40, why diagram-only claims
stay `DISPUTED`, and why six images are human-verified once
([05](../05-extraction-pipelines.md#diagrampipeline--diagramspng)). A design that assumed reliable
diagram extraction would be assuming something the field has measured as false.

---

## <a id="prompt-injection"></a>Prompt injection and RAG security

- OWASP — [*LLM Prompt Injection Prevention Cheat Sheet*](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- [*SoK: Agentic Retrieval-Augmented Generation — Taxonomy, Architectures, Evaluation*](https://arxiv.org/pdf/2603.07379)
- [*Hidden-in-Plain-Text: A Benchmark for Social-Web Indirect Prompt Injection in RAG*](https://arxiv.org/pdf/2601.10923)
- [*CleanBase: Detecting Malicious Documents in RAG Knowledge Databases*](https://arxiv.org/pdf/2605.00460)

**Taken.** Treat every retrieved chunk as untrusted user input; agentic RAG compounds
the risk because each retrieval step is a fresh injection opportunity; five crafted
documents can steer responses ~90% of the time; MCP tool descriptions are themselves
untrusted input and servers should be pinned rather than dynamically discovered.

Our structural defence falls out of the CQP split: **the planner never sees retrieved
content**, so corpus text cannot influence which query runs
([07](../07-api-and-mcp.md#security)).

---

## <a id="semgrep"></a>Static security analysis

- [*Semgrep\*: Improving the Limited Performance of SAST Tools*](https://dl.acm.org/doi/fullHtml/10.1145/3661167.3661262)
- [*Memoir: Learning, Verifying, and Evolving False-Positive Memories for SAST Tools*](https://arxiv.org/pdf/2608.09181)
- [*Uncovering CWE-CVE-CPE Relations with Threat Knowledge Graphs*](https://arxiv.org/pdf/2305.00632)

**Taken.** CWE identifiers as the standardised risk taxonomy on `Risk` nodes, and the
documented limitation that Semgrep's default configuration misses instances while
tuning for precision — several frequently-confirmed vulnerability classes are flagged
by neither Bandit nor Semgrep. Hence: pattern findings are `DISPUTED` until a second
source corroborates ([05](../05-extraction-pipelines.md#codepipeline--apps-packages)).

---

## <a id="contradiction"></a>Contradiction and documentation drift

- [*CASCADE: Detecting Inconsistencies between Code and Documentation with Automatic Test Generation*](https://arxiv.org/pdf/2604.19400)
- [*READU: Inconsistency-Driven Just-in-Time Detection and Repair of README Bugs*](https://arxiv.org/pdf/2607.15780)
- [*Measuring LLM Trust Allocation Across Conflicting Software Artifacts*](https://arxiv.org/pdf/2604.03447)
- [*Improved Evidence Extraction and Metrics for Document Inconsistency Detection with LLMs*](https://arxiv.org/pdf/2601.02627)

**Taken, and it changed the design.** The finding that matters: *LLMs should not be
used as stand-alone code-drift detectors* — documentation faults are caught at 67–94%
but code-only drift at far lower rates, and they should be deployed as documentation
auditors, not autonomous drift detectors. Hybrid NLI + LLM-judge beats either alone,
and cross-document contradiction remains hard.

This is why our contradiction detection is **structural rather than semantic**: we
compare claims about the same `(subject, predicate, object)` with explicit negation
and supersession handling ([04](../04-temporal-model.md#resolution-algorithm)), and
use the model for modality classification only. Asking a 7B model "do these two
documents disagree?" is precisely the usage the literature says fails.

---

## <a id="incremental-etl"></a>Incremental and idempotent ingestion

- [*Idempotent Data Pipelines: Safe to Re-Run Every Time*](https://fawadhs.dev/blog/idempotent-data-pipeline-design-safe-rerun)
- [*Incremental ETL on S3 with CocoIndex*](https://cocoindex.io/blogs/s3-incremental-etl/)
- [Content-addressed index caches — PIIIX/chapters #684](https://github.com/PIIIX-org/chapters/issues/684)

**Taken.** Content hash as identity rather than path or mtime (handles renames and
re-delivery); cache keyed by **blob hash + extractor/embedder version**, so a version
bump invalidates one pipeline rather than the corpus; deterministic content-derived
record IDs making re-runs an upsert. A sync with no changes must do no work.
That is [05](../05-extraction-pipelines.md#incremental-by-construction) exactly.

---

## <a id="context-engineering"></a>Context engineering

- Thoughtworks — [*Context rot in AI agents: how to recognize and fix it*](https://www.thoughtworks.com/insights/blog/generative-ai/what-is-context-rot)
- [*Context Engineering in 2026: Why We Stopped Compacting Our Agent's Context*](https://www.louisbouchard.ai/context-engineering-2026/)
- [*Tokalator: A Context Engineering Toolkit for AI Coding Assistants*](https://arxiv.org/pdf/2604.08290)

**Taken.** Accuracy degrades as the window fills (lost-in-the-middle, now "context
rot"); just-in-time retrieval keeping context small measurably improves accuracy and
speed, with ~40% token reduction at equivalent retrieval quality. This is why
`token_budget` is enforced rather than advisory
([06](../06-retrieval.md#context-budget)). The related finding that summarisation
dropped in-session recall from 92% to roughly a third while costing ~2× is a direct
argument against the summarise-everything index layer we had considered.

---

## <a id="mcp-design"></a>MCP server design

- [*Best Practices for Building Production-Grade MCP Servers for AI Agents*](https://www.zenml.io/llmops-database/best-practices-for-building-production-grade-mcp-servers-for-ai-agents) (Prefect)
- [*10 strategies to reduce MCP token bloat*](https://thenewstack.io/how-to-reduce-mcp-token-bloat/)
- [*MCP Server Best Practices: Optimizing Performance for AI Agents*](https://goclaw.sh/blog/mcp-server-best-practices)

**Taken.** MCP is a user interface for agents, not a REST wrapper — design top-down
from what the agent is accomplishing; respect the token budget (roughly 40% of token
usage can go to MCP metadata in some environments; ~50 tools across all servers is a
practical ceiling); expose aggregation tools that compute server-side rather than
returning raw rows. Six workflow-shaped tools, measured at under 2,000 schema tokens
([07](../07-api-and-mcp.md#mcp-tool-design)).

---

## <a id="single-store"></a>Store selection

- [*Open Source Knowledge Graph & GraphRAG Databases Compared (2026)*](https://arcadedb.com/blog/open-source-knowledge-graph-graphrag-databases-compared/)
- [*GraphRAG Frameworks in Production: Microsoft GraphRAG, LightRAG, Neo4j GenAI, Kùzu*](https://www.llms.blog/posts/graphrag-frameworks-and-architectures-in-production-comparing-microsoft-graphrag-lightrag-neo4j-genai-and-kuzu)
- [*PostgreSQL as a Graph Database: CTE + pgvector + pg_trgm*](https://nevrai.com/blog/postgresql-as-graph-database/)
- [*Vector Database Benchmark: 7 Open-Source Engines for RAG*](https://aimultiple.com/open-source-vector-databases)

**Taken.** Neo4j, Memgraph, Kùzu and FalkorDB all now ship native HNSW vector
indexes, enabling subgraph traversal combined with semantic search in a single query
with no separate vector DB — and Neo4j remains the mature default with the largest
ecosystem. That single-engine property is the whole basis of
[ADR-0001](../adr/0001-single-store-neo4j.md).

**Also noted.** Postgres with recursive CTEs is measured at 0.34/0.42/0.95 ms p50 at
1/2/3 hops and is genuinely sufficient below ~10k nodes / 50k edges — which is our
corpus. We record this as the serious alternative we did not take, because the team
chose Neo4j for Cypher ergonomics and demo legibility.

### <a id="kuzu"></a>Kùzu status

- [*KuzuDB, the Promising Embedded Graph Database, is Suddenly Archived*](https://biggo.com/news/202510130126_KuzuDB-embedded-graph-database-archived)
- [*Kùzu's Legacy and the New Wave of Embedded Graph Databases*](https://gdotv.com/blog/kuzu-legacy-embedded-graph-database-landscape/)

Archived 2025-10-10 and read-only; an EU DMA filing surfaced in February 2026 showed
Apple had agreed to acquire Kùzu Inc. on 2025-10-09. Community forks exist
(LadybugDB, Bighorn, a Vela Partners fork). **Excluded on maintenance risk**, despite
being the otherwise-ideal embedded fit.

---

## <a id="embeddings"></a>Embedding and reranking models

- [*Best Embedding Models for RAG (2026): Ranked by MTEB Score, Cost, and Self-Hosting*](https://www.premai.io/blog/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/)
- [*Qwen3 Embedding: Advancing Text Embedding and Reranking Through Foundation Models*](https://arxiv.org/pdf/2506.05176)

**Noted.** On MTEB English v2 (October 2026) the leading open-weight models are
QZhou-Embedding (75.97) and Qwen3-Embedding-8B (75.23), both Apache 2.0;
Qwen3-Embedding-8B also leads MTEB-Code and handles NL and code natively; the Qwen3
rerankers outperform baseline reranking methods.

**Chosen anyway:** `nomic-embed-text` (768-d) for the build, because an 8B embedding
model on a laptop alongside Neo4j and a generation model is not a five-hour
proposition. Dimension is configuration, so the upgrade is a re-index.

---

## <a id="rag-evaluation"></a>Evaluation

- [*Evaluating Retrieval Augmented Generation using RAGAS*](https://superlinked.com/blog/evaluating-retrieval-augmented-generation-ragas)
- [*LLM Readiness Harness: Evaluation, Observability, and CI Gates for LLM/RAG Applications*](https://arxiv.org/pdf/2603.27355)
- [*Retrieval Improvements Do Not Guarantee Better Answers: A Study of RAG for AI Policy QA*](https://arxiv.org/pdf/2603.24580)

**Taken.** Faithfulness decomposes an answer into claims and verifies each against
retrieved evidence — structurally what our span gate does at ingest rather than at
answer time. Golden sets should be built from manually verified contexts and answers.
And the warning that retrieval improvements do not guarantee better answers is why we
assert answer, status *and* citations separately
([09](../09-evaluation.md#the-golden-set-is-the-trap-catalogue)).

---

## <a id="observability"></a>Observability

- [*RAG Pipeline Observability: What to Trace at Every Stage*](https://last9.io/blog/rag-pipeline-observability/)
- [*Best RAG observability tools (2026)*](https://www.braintrust.dev/articles/best-rag-observability-tools-2026) (Braintrust)

**Taken.** OpenTelemetry GenAI semantic conventions (`gen_ai.operation.name`,
`gen_ai.retrieval.query.text`, `gen_ai.usage.*`) — pre-1.0 but the direction the
ecosystem is converging on; trace prompt construction, retrieval, tool calls and
evaluation scoring as separate spans; run LLM-as-judge scoring on 10–20% of
production traffic rather than all of it.

---

## <a id="contract-first"></a>Parallel delivery

- [*Contract-First Integration: A Practical Guide for Developers*](https://dev.to/wallaceespindola/contract-first-integration-a-practical-guide-for-developers-49nf)
- [*Schema-First API Development and Testing Strategy (2026 Playbook)*](https://totalshiftleft.ai/blog/schema-first-api-development-testing-strategy)

**Taken.** Freeze the contract, generate mocks, let every stream build against the
mock rather than against each other. Applied to a data pipeline rather than an HTTP
boundary: the frozen `ClaimRecord` plus `claims-sample.jsonl` is our mock server, and
it is what makes [08](../08-delivery-plan.md#contracts-frozen-in-the-first-30-minutes)
work at all.
