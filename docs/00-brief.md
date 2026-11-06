# 00 — The brief and the scoring

Source: the printed hackathon pack, *"Efficient AI Context Service for Enterprise
Engineering Knowledge"* (AT&T Hackathon), transcribed from photographs of pages 1–9
on 2026-11-06. Sections 3 (*Implementation Hint*) and 4 (*Target Deliverable for the
PoC*) were not photographed and are **not** reflected here — see [Gaps](#gaps).

## The ask

> Build an efficient, AI-powered Context Service that maps connections across
> scattered engineering knowledge, marks source contradictions, flags security risks,
> fills the gaps, and provides evidence-backed insights.

Tagged: *Knowledge Graph · Multi-Modal AI · Ontology*.

The stated shape is **scattered sources → advanced agentic ETL → unified, queryable
context**, surfaced to an IDE through MCP/API:

```
Collect multiple      Apply engineering      Discover relationships
technical sources ──▶ and AI mindset    ──▶  Explain relationships  ──▶ Context ──▶ MCP/API ──▶ IDE
                      (how / what /          Detect gaps or conflicts    Service
                       when to extract)      Flag security concerns
                                             Provide source evidence
```

> The goal of this hackathon is to build an advanced agentic ETL to build the Context
> Service. The agentic ETL will classify, map, validate, and enrich incoming data
> against the predefined ontology.

## The four challenge scenarios

| Scenario | Challenge | What the Context Service must do |
|---|---|---|
| Change code in repo A | May impact code elsewhere | Define the relationship between repositories |
| Stale documentation | Wiki describes an outdated schema; code has moved on | Detect the difference, decide which source is more current — *by time, meeting notes, and other facts* — and explain the inconsistency with evidence |
| Knowledge only in a diagram | A diagram holds information absent from the code | Extract it, connect it to related sources, represent it as evidence-backed context |
| Insecure patterns | Code contains security issues | Detect, flag, and ensure generated code does not repeat them |

## The scoring, and what it implies

| Judging area | Points | What it rewards |
|---|---:|---|
| Extraction Approach | 15 | Ingest/extract from scattered sources; **automated**; **handles different formats** |
| Knowledge Representation | 25 | Ontology, schema and structures; representing a source from **multiple perspectives** — concepts, policies, systems, relationships, dependencies, risks, evidence; how knowledge is structured, validated, stored, indexed and retrieved (graph DB / text KG / vector DB / hybrid), **keeping the context trustworthy** |
| Context Service Connection and Usage | 15 | Usable by humans, IDEs and agentic coding assistants via MCP, APIs or similar |
| Presentation and Explanation | 35 | Clarity of the **engineering and AI thinking**: design, architecture, reasoning, trade-offs, limitations, implementation approach |
| Forward View | 10 | Scaling, maintenance, integration into real developer workflows, staying accurate/secure/trustworthy over time |
| **Total** | **100** | |

The pack states this explicitly:

> Participants may have different levels of access to LLM and VLM models. Therefore,
> the most important judging criterion is not only the output itself, but how clearly
> the team explains the engineering and AI thinking behind the solution, including the
> design decisions, validation approach, limitations, and how the solution could be
> improved in the future.

**Consequence for us.** 45 of 100 points (Presentation + Forward View) are won by
*reasoning that is written down*, and a further share of Knowledge Representation is
won by the ontology document rather than by running code. Against a five-hour build
budget this is the decisive fact: see [08 — delivery plan](08-delivery-plan.md).
We optimise for *a small system that is completely explained*, not a large system
that is half-built.

## The honesty requirement

The pack is unusually direct about what *not* to build:

> The Context Service should not blindly connect everything. It should distinguish
> verified facts from assumptions, outdated information, contradictions, weak
> evidence, and security concerns.

And it warns the corpus is seeded with traps on purpose: outdated docs describing a
removed API; two diagrams that contradict each other; unrelated projects that happen
to share an API name; security issues that must not be propagated into generated
code; release notes citing undocumented dependencies; a wiki schema that disagrees
with the source.

> This imperfect information is intentional, but it is inspired by the reality of how
> enterprise repositories often look.

A system that answers confidently from the highest-cosine chunk will score badly
here, because the highest-cosine chunk is frequently the stale one. This single
observation drives the whole architecture: see [04 — temporal model](04-temporal-model.md).

## The eight declared source types

The pack enumerates what the corpus contains and hints at what each is good for:

1. **Source code** — Python, JavaScript, config, dependency manifests, tests, READMEs. *Inspect actual implementations and identify dependencies.*
2. **System design diagrams** — PNG/SVG architecture, sequence, ERD, service-interaction drawings. *Compare intended architecture with the actual implementation.*
3. **Wiki and documentation** — Markdown on APIs, business requirements, authentication, deployment, architecture decisions, troubleshooting. *Explains purpose and intended behaviour.*
4. **API specifications** — OpenAPI YAML/JSON, example requests/responses, event schemas, integration contracts. *Identify connections between services.*
5. **Architecture decisions and meeting notes** — design proposals, migration plans, technical meeting summaries, ADRs, change requests. *Explain why a system was designed a certain way; reveal relationships not obvious from code.*
6. **Database schemas and data models** — SQL schemas, ERDs, migration files, sample records. *Connect applications to shared data models and databases.*
7. **Issues, bug reports, release notes** — issue descriptions, changelogs, deprecation notices, planned integrations, production issues, outage notes, synthetic tickets. *Reveal outdated documentation, planned integrations, and dependencies that changed over time.*
8. **Dependency and deployment configuration** — `requirements.txt`, `package.json`, Dockerfiles, Compose, CI workflows, Terraform, Kubernetes manifests, environment config. *Reveal shared libraries, deployment relationships, runtime and infrastructure dependencies.*

These eight map directly onto our six extraction pipelines — see
[05 — extraction pipelines](05-extraction-pipelines.md). Type 7 is called out by the
pack as the primary carrier of *temporal* signal, which is why it feeds the status
resolver rather than just the search index.

## Gaps

Two sections of the pack were not captured and are therefore not designed against:

- **§3 Implementation Hint** — may constrain stack or approach.
- **§4 Target Deliverable for the PoC** — defines what must literally be handed in.

**Action before implementation starts:** obtain both sections and diff them against
[08 — delivery plan](08-delivery-plan.md). If §4 names a required artefact we are not
producing, it outranks our plan.
