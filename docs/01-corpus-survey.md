# 01 — Corpus survey

Everything below was read from `vendor/att-hackathon-task` at submodule commit
`612cc0b`. Nothing is taken from the upstream README's self-description.

## Shape and scale

374 files, 3.3 MB, excluding `.git` and `node_modules`.

| Extension | Count | Where |
|---|---:|---|
| `.md` | 135 | `docs/ wiki/ meeting-notes/ issues/ incidents/ releases/ api-specs/ archive/ apps/*/README.md` |
| `.json` | 93 | `package.json`, OpenAPI specs, fixtures, `config/ports.json` |
| `.tsx` / `.ts` / `.js` / `.mjs` | 88 | twelve apps + seven shared packages + build scripts |
| `.sql` | 7 | `apps/*/migrations/`, `archive/facilities-tracker/schema.sql` |
| `.png` | 6 | `diagrams/` |
| `.py` | 2 | `apps/inventory-service/` |
| `.java` | 1 | `apps/hr-service/` |
| `.yaml` / `.yml` | 4 | `compose.yaml`, `pnpm-workspace.yaml`, CI |
| `.graphql` | 2 | `apps/api-gateway/`, `archive/facilities-tracker/schema.graphql` |

**This number matters more than any other in this document.** At 374 files the whole
corpus fits in a laptop's page cache. Every "scale" argument in this design is about
*the shape of the solution*, not about the size of this input — see
[Forward view](09-evaluation.md#forward-view) for where the shape breaks.

### Structural inventory

- `apps/` — twelve deployables: `api-gateway` (GraphQL, TS), `user-service`,
  `order-service`, `payment-service` (TS), `inventory-service` (Python/Flask),
  `hr-service` (Java 21), `storefront` (Next.js), `admin`, `hr-portal` (Vite/React),
  `blog` (Remix), `customer-mobile`, `employee-mobile` (Expo).
- `packages/` — seven shared libraries: `ui`, `logger`, `http-client`,
  `demo-identity`, `config-eslint`, `config-typescript`, `jest-presets`.
- `docs/` — 5 ADRs, plus `architecture/`, `design/`, `how-to/`, `reference/`, `runbooks/`.
- `wiki/` — 10 team handbook pages, each dated in prose.
- `meeting-notes/` — 16 files, `YYYY-MM-DD-slug.md`, January–September 2026.
- `incidents/` — 5, `issues/` — 12, `releases/` — 5, all date-stamped.
- `api-specs/` — 6 services × (Markdown + OpenAPI JSON), plus `history/` holding
  superseded contracts.
- `diagrams/` — 6 PNGs, January–September 2026, plus a README that tells you how to read them.
- `archive/` — two abandoned project fragments.
- `config/ports.json` — the single machine-readable service→port map.

## Metadata reality check

**There is no front matter anywhere.** Dates and statuses are prose:

- ADRs: `Date: 2026-06-04` / `Status: Accepted` on lines 3–4 — regular, parseable.
- Wiki: `Core Platform handbook · 2026-02-17` — a byline, format varies per page.
- Issues: `Open · 2026-09-11` — status and date on one line.
- Meeting notes / incidents / releases: date in the **filename**, sometimes repeated in prose.
- Code, config, OpenAPI: no dates at all. Their time signal must come from the
  migration/release/ADR records that reference them.

**Design consequence.** A date extractor cannot be one regex. It is a per-pipeline
concern with a per-source-type confidence, and files with no intrinsic date inherit
time from the git history and from records that cite them. See
[04 — temporal model](04-temporal-model.md#where-time-comes-from).

## The trap catalogue

These are the seeded contradictions, found by reading. Each is a test case: a
correct Context Service resolves all seven and *shows its working*. They are the
golden set in [09 — evaluation](09-evaluation.md).

### T1 — Removed infrastructure still documented (temporal supersession)

| Source | Says | Date |
|---|---|---|
| `wiki/inventory-service.md:5` | "Core Platform owns Stock and its **Redis read cache**… writes invalidate the cache" | 2026-02-17 |
| `diagrams/architecture-january.png` | Stock ──catalog read──▶ **Redis read cache** | 2026-01 |
| `meeting-notes/2026-06-04-cache-removal.md` | "read products and availability from SQLite directly" | 2026-06-04 |
| `docs/adr/003-stock-cache.md:3-6` | `Status: Accepted` — "Remove Redis from the local inventory path" | 2026-06-04 |
| `releases/2026-06-v1.3.md` | "Removed the Redis path and `REDIS_URL`" | 2026-06 |
| `diagrams/architecture-september.png` | no cache node at all | 2026-09 |

Correct answer: **no cache on the current availability path.** The wiki page and the
January diagram are `DEPRECATED` as of 2026-06-04, not wrong-at-the-time. The
incident file even says so itself: *"It does not establish that a cache still sits on
the September availability path."*

A naive retriever ranks `wiki/inventory-service.md` first — it is the most
topically on-point document for "how does stock caching work". That is the failure
this system exists to prevent.

### T2 — Schema drift between wiki and migrations

`wiki/accounts-http.md:5` (2026-02-03) documents the response as `id, name, email,
status`, and line 7 says *"Business tiers remain a proposal, so client code can
default to standard."*

`apps/user-service/migrations/002-account-tiers.sql:1-2`:

```sql
ALTER TABLE users RENAME COLUMN status TO account_status;
ALTER TABLE users ADD COLUMN customer_tier TEXT NOT NULL DEFAULT 'standard';
```

Both wiki claims are now false: the column is `account_status`, and tiers shipped.
This is the pack's "stale documentation" scenario in literal form, and it is
resolvable **deterministically** — a migration file is machine-readable ground truth
about a schema, outranking prose. See [04](03-ontology.md#source-authority).

### T3 — Superseded API contract

`api-specs/history/accounts-v1.md` — "Published 2026-01-20 for demo 0.8… Customer
tier has no response field in this contract. **Compare release records before using
the winter contract to generate a new client.**"

A path containing `/history/` is a deterministic deprecation signal. Anything
generated against `accounts-v1` is generating against a dead contract.

### T4 — Shared attribute that is not a join key

`wiki/accounts-http.md:9` — *"a shared email is not a documented foreign key."*
`docs/design/people-account-link.md:6` — *"An explicit properties file maps selected
`emp-` identifiers to `cus-` identifiers… It does not infer identity from display
name or email."* `wiki/inventory-service.md` — *"A display name is not a stock key."*

The corpus is explicitly defending against entity resolution by string similarity.
**Any automatic entity-merge on name or email would be wrong here, by design.**
Our resolver therefore merges on declared identifiers only, and records
name/email overlaps as a `SIMILAR_NAME_TO` observation with
`status: DISPUTED` — never as identity. See [03](03-ontology.md#entity-resolution-policy).

### T5 — Name collisions across unrelated projects

- `archive/conference-registration/src/PaymentService.ts` — README line 5:
  *"PaymentService is a voucher calculator, not a payment-network adapter. User means
  an attendee in this project."* Paused 2026-04-23, no entry point, no deployment profile.
- `archive/facilities-tracker` — *"The Inventory model tracks assigned office assets
  by room and custodian. It does not contain the sellable Northstar product catalog."*

Two `PaymentService` classes and two `Inventory` models that must not be unified.
Scoping by **workspace membership** (`pnpm-workspace.yaml`, `turbo.json`,
`compose.yaml` profiles) separates them deterministically: `archive/` is outside the
active workspace.

### T6 — Proposal mistaken for decision

`docs/adr/004-people-sso.md:3-4` — `Date: 2026-08-06`, `Status: Proposed`.
Body: *"This proposal must not be interpreted as an approved SSO rollout."*
Unresolved: issuer, subject lifecycle, offboarding, approver.

A system with only two states (current / stale) must call this current, and will
tell an engineer that SSO exists. It needs a third state. This is the direct
corpus justification for the `PROPOSED` / `PLANNED` statuses the user asked for.

Related forward-looking statements elsewhere: *"The warehouse console migration is
**scheduled after** gateway adoption"* (`wiki/inventory-service.md:9`), and
*"an effective date next month"* (`meeting-notes/2026-06-04-cache-removal.md`).

### T7 — Security concern recorded as an open question

`issues/SEC-22.md:3-7` — `Open · 2026-09-11`. Order-list filtering honours the
synthetic customer header; *"Review individual order lookup using a record owned by a
different customer and compare the branches."* That is a broken-object-level-
authorisation shape (CWE-639) stated as a hypothesis, not a confirmed finding.

The right behaviour is a `Risk` node with `status: DISPUTED` and
`confidence: reported-not-verified`, linked to the handler it names — **plus** a
static-analysis claim from the code itself if one can be produced. Two independent
signals agreeing is what promotes it to `VALID`. One signal alone is a lead.

## What the corpus tells us to build

Reading the seven traps together, the corpus is not asking for better retrieval.
Every trap is a case where the *most relevant* text is the *wrong* text, and the
correction lives in a different file, of a different type, written at a different
time. The system therefore needs, in order of importance:

1. **Time on every assertion** — T1, T2, T3, T6 are all unanswerable without it.
2. **Source authority ranking** — T2 and T3 resolve deterministically once you accept
   that a migration outranks a wiki page and `/history/` outranks nothing.
3. **Conservative entity resolution** — T4 and T5 are *anti*-joins. The corpus
   punishes eagerness.
4. **Claims, not facts** — T6 and T7 must be representable as "someone proposed this"
   and "someone suspects this", which a plain subject-predicate-object graph cannot say.

That ordering produces the architecture in [02](02-architecture.md).
