# 0012 — Diagram evidence: deterministic geometry first, a model last

Status: Accepted (2026-11-08) — option 3 staged; the owner chose automatic extraction, a
zero-GPL default stack, and a bounded human-assist mode
(extends [0011](0011-evidence-layer.md); **supersedes nothing yet** — see the precedent below)

## Context

Six diagrams sit in the corpus and **none of them is reachable by any query**:

```
$ find vendor/att-hackathon-task -type f \( -iname '*.png' -o -iname '*.svg' \) | wc -l
6                      # all PNG; zero SVG/XML
$ cli index
skip att-hackathon-task/diagrams/customer-orders-erd.png: no UTF-8 text in its first bytes
```

The walker skips them because it reads UTF-8 text, and the text beside them (captions,
`diagrams/README.md`) is not the diagram. So a question whose answer only exists in
`architecture-september.png` returns nothing, and the product's claim — every claim points at
a corpus file — has a hole exactly where system architecture lives.

The shipped image holds no `numpy`, no `Pillow`, no OCR binding; `tesseract` is not installed.
Any option below is therefore a dependency decision, not just a code decision.

## Precedent this ADR missed

A hostile review found what a first draft should have: **this repository already decided** how to
handle these six files.

- `docs/adr/0006-scope-of-the-build.md:38-40` — "`DiagramPipeline` VLM extraction — **replaced by six
  human-committed fixtures** under `data/fixtures/diagrams/`". Status: Accepted.
- `docs/05-extraction-pipelines.md` carried the same instruction in its diagram section; this
  session amended that paragraph in the same commit as this ADR, which is why the current file says
  the opposite. The quote lives in git history, not in the working tree — an ADR must not cite text
  it replaced.
- `AGENTS.md` invariant 4 already blesses `data/fixtures/` as the one exception to "no derived data".

That option was never built (`ls data/fixtures/` → only `claims-sample.jsonl`), and this ADR's first
draft ignored it. Re-opening a decision requires a superseding ADR that names the old one and prices
it; that is what option 5 below does, and why this ADR is blocked rather than accepted.

## Options

1. **Do nothing, document the gap.** Honest and free. Leaves six files, including two
   architecture diagrams, unanswerable, and leaves "context service" unable to see pictures.
2. **OCR text only.** `tesseract-ocr` + `pytesseract` + `pillow`: text blocks with boxes become
   a searchable chunk per diagram, and each block becomes a low-confidence `MENTIONS` claim when
   the text names a known entity. No shape reasoning, no edges. Deterministic given a pinned
   OCR build; measured cost on the six files, not assumed.
3. **Full deterministic geometry.** Add `numpy` + `opencv-python-headless`: binarise, find
   connected components, detect rectangles and lines, place arrowheads at line ends, link a line
   to the boxes its endpoints fall inside, and label each box from the OCR text inside it. Emits
   `DIAGRAM_EDGE` claims with `in`/`out`/`inout` direction and `confidence ≈ 0.6`. Largest
   payoff, largest dependency, and it fails silently on hand-drawn or gradient-filled diagrams.
4. **Vision model describes the picture.** `llava` (4.7 GB) or similar via the existing ollama.
   Cheap to wire, unfalsifiable in the wrong direction: a VLM asked "what does this architecture
   diagram show" will confidently name services that are not in it, which is the exact failure
   this corpus was seeded to punish.

5. **Human-reviewed fixture, as ADR-0006 already decided.** No dependency: the diagram is read once
   (a human, or a model whose output a human checks), the result committed as
   `data/fixtures/diagrams/*.json` with `extractor: "human+vlm"`, cited to the PNG by the same
   **region**. It needs the identical citation-contract work as option 3 and produces *better* text:
   measured, OCR reads `customerId` as `customerld`, and the six-diagram inventory was already read
   end to end this session. What it cannot do is absorb a **new** image without a human.

## Decision

Option 3, but **staged and gated** — each stage must prove its value on the six real files
before the next is built, and every stage is deterministic except the last:

| stage | dependency | emits | gate to pass |
|---|---|---|---|
| 1. text | `rapidocr` + `onnxruntime` (**no GPL**), `ingest/diagram.py` | one chunk per diagram (text blocks in reading order), OCR tokens with boxes + `MENTIONS` claims | the ERD question below returns that diagram's text as evidence |
| 2. geometry | `opencv-python-headless` + `numpy` + `networkx`, same module `ingest/diagram.py` | `DIAGRAM_NODE` (box + label), `DIAGRAM_EDGE` (source, target, direction, line style) | edges agree with the two architecture diagrams a human reads; ≥80% of arrows on the two diagrams named as trustworthy below |
| 1b. alternative text reader | `tesserocr` (**GPL-2.0-or-later**, jbigkit vendored in the wheel), its own module `ingest/diagram_tesseract.py`, extra `diagram-tesseract`, behind ADR-0013's gate | the same text signal, used for the character-level vote | must beat or tie the default on the ERD question, and never be required |
| 3. model assist | none new (ollama `llava`) | a *hypothesis* list of edges, each one required to cite a detected box pair; unreferenced model output is discarded | hypothesis must never introduce an entity absent from stages 1–2 |

### Automatic first; a person is a degradation path, never the process

At a thousand images there is nobody to describe each one, so the **default is automatic**
extraction, and the pipeline must be able to run unattended end to end. A human appears only in
an explicitly requested review mode, which:
1. is refused above `settings.HUMAN_ASSIST_MAX_FILES` (default 20) — the count is the guard
   against the mode quietly becoming the workflow;
2. writes the same claim shape as the automatic route (`extractor: "human+assisted"`), so nothing
   downstream learns a second format;
3. remains a *review* of what was extracted, not the only way the text is obtained.

This revises what [ADR-0006](0006-scope-of-the-build.md) assumed (six fixtures instead of a
pipeline) rather than replacing its intent: fixtures were the right answer for six files and the
wrong answer for a corpus that may hold thousands.

### Licence boundary: GPL-class code is opt-in, not linked into the default

The licence rule is enforced by `ingest/optin.py`, already in the code (ADR-0013 for the mechanism):
the OCR module lives in its own file, installs from its own `pyproject` extra, imports its
dependency lazily, and the walk asks `N file(s) would be extracted … enable diagram-ocr? [y/N]`
before anything runs. Declining yields byte-identical output to a build without it, so the service
stays usable and MPL-clean without the GPL part.

Whether the default stack stays clean depends on which component is copyleft and whether it can be
dropped — measured separately, see the licence note in the consequences.

### One engine is not trusted alone: fuse the signals

Published systems are mostly single chains where later stages trust earlier ones, so nothing can
disagree with anything. This one fuses at four levels, with the design and its citations in
[research/diagram-extraction-fusion.md](../research/diagram-extraction-fusion.md):

| level | inputs | rule |
|---|---|---|
| character | OCR under ≥2 configurations | ROVER alignment vote before anything else |
| label | both OCR configs, box clustering, ontology resolver, optional VLM | similarity vote, accept at `score ≥ 0.60` **and** margin `≥ 0.15`, else keep alternatives |
| edge | box anchoring, arrowhead, line coverage, optional VLM | geometric vote only — **text never creates an edge** |
| graph | all | schema filter, never edge generation |

`conf(e) = Σ(wᵢ·aᵢ)/Σ(wᵢ)` with `w = {box .30, arrow .30, line .25, vlm .15}` and ternary
`aᵢ ∈ {0, 0.5, 1}`. The score is an **ordinal band**, not a probability: six diagrams cannot
support a calibration fit. Anchoring is a hard rule, taken from TRACE — an edge whose arrowhead or
box endpoint fails to verify is demoted and flagged `needs_review`, never promoted to a fact.

Quality is measured without ground truth, so a bad read is visible with no human: cross-method
label disagreement, OCR confidence distribution, label-to-box containment, connector anchoring
rate, topology sanity (density, isolated nodes, cycles where a DAG is expected), label
resolvability against the ontology, and byte-reproducibility. `(customerId → customerld)` is what a
resolvability drop looks like; the 8/40 line drift between engines is what a reproducibility drop
looks like.

Stage 3 is behind a flag and off by default, for the same measured reason the vocabulary
resolver is: a generative model is not an improvement when a deterministic reader exists
([ADR-0010](0010-semantic-claims-and-effort.md)).

### Measured cost, and why the dependency set changed

| route | added image size | licence | notes |
|---|---|---|---|
| `tesseract-ocr` + `tesseract-ocr-eng` (first draft) | **+117 MB** | GPL-2.0+ | pulls 70 packages: ICU (32 MB `libicudata`), cairo, fontconfig, fonts |
| `tesserocr` + tessdata (second draft) | **+37.2 MB** | **GPL-2.0+ — jbigkit vendored in the wheel, mapped at import** | cannot be made clean: deleting the `.so` breaks the import |
| **`rapidocr` + `onnxruntime` + `opencv-headless` + `numpy` + `pillow` + `networkx` (chosen)** | **+325 MB** | **LGPL-2.1 only** (FFmpeg, GEOS), no GPL | one set serves OCR *and* geometry; `rapidocr` already requires headless OpenCV |

`libgl1` and `libglib2.0-0t64` are **not required** — measured: `import cv2` plus
`connectedComponentsWithStats` work on a base image where `dpkg -l libgl1` finds nothing.

Measured, and the reason the default changed: `libjbigkit` is not an optional parser behind a
TIFF branch — `import tesserocr` maps `libjbig-*.so.2.1` into the process, and the wheel ships
no GPL-2 text or source offer. A GPL library that any import reaches is not "contained in an
opt-in module"; it is in the venv. The zero-GPL default costs 288 MB more and buys a default
install that carries no strong copyleft at all. Notices are in
`apps/context-service/THIRD_PARTY_NOTICES.md`.

### OCR output is not verbatim, so a region replaces the line

Measured on the real files: `customerId` in `customer-orders-erd.png` reads as **`customerld`**
(31 corpus occurrences of the former, 0 of the latter). That is the whole reason this ADR is
needed rather than a text-extraction patch: OCR text can never satisfy a verbatim span gate, so an
image claim is cited by **region**, and the verification legs are geometric.

Determinism is worse than a version string. Same `eng.traineddata`, same PSM: tesseract **5.5.0**
(Debian) and **5.5.3** (the wheel) agree on three diagrams and disagree on three —
8 of 40 lines differ on `checkout-sequence` (`leave snapehts` → `leave snapshots`). PSM 3 reads
`OST /v1/orders`; PSM 6 reads `POST /v1/orders`. Measured repeat runs are byte-identical, so the
drift is version-bound, not run-bound. Therefore `extractor_version` must include
`tesseract_version()` (5.5.3 / leptonica-1.87.0), the `eng.traineddata` SHA-256, `psm`, `oem: 1`
and `lang: eng` — and the determinism test hashes sorted claim JSON per file rather than tolerating
a text distance.

Two rules carry over unchanged from ADR-0011:

- **A diagram passage is evidence, not a verdict.** Text read out of a picture carries no
  status; geometry claims carry `confidence ≈ 0.6` and the `extractor` that produced them, so a
  reader can tell a DDL parse (0.98) from an arrow guessed at a corner.
- **Determinism.** Same input, same extractor version → byte-identical claims. OCR build and
  OpenCV version are part of `extractor_version`; a silent OCR upgrade must invalidate the
  diagram claims rather than quietly change them.

### What the build proved (2026-11-08)

- The gate holds end to end: `what declared type does orders.total have` answers
  **`Orders.total HAS_DECLARED_TYPE REAL (USD)`** cited to
  `customer-orders-erd.png` region `[628, 336, 193, 26]`.
- The id promise held: all 284 regenerated claim ids were already present in the graph
  loaded before the change.
- Versioning did real work: dropping per-line text claims required bumping
  `extractor_version` to `v2`, and the load then removed 112 stale v1 claims (the first
  attempt left them because the version had not changed).
- Geometry did not reach the gate: 0-2 of ~8 edges per diagram, so edges stay unemitted.

### Measured on the corpus before writing any extractor

`rapidocr` + `onnxruntime` (the default, GPL-free set) was run against the real files on
2026-11-08. It answers both pixel-only questions exactly, and repeats byte-identically:

| input | measured |
|---|---|
| `customer-orders-erd.png` | 18 lines, including **`total: REAL (USD)`** verbatim |
| `people-finance-process.png` | 10 lines, including **`Friday 16:00: manually prepare approved-leave CSV`** |
| `customerId` (the label tesseract mangled) | read as `customer_id` correctly |
| repeat runs, three diagrams | identical text **and boxes** (sha256 of sorted output) |
| runtime | 1.3 s first call (model load), ~1.4 s per diagram after |

That removes the "is the gate even reachable" risk before phase 3c starts, and it means the
gated GPL reader is an *alternative* to compare against, never a requirement.

### The stage-1 gate, corrected against the pixels

The first draft gated on `checkout-sequence.png`. Its answers leak: `402` appears in
`api-specs/order-service.openapi.json:124` and `docs/reference/order-lifecycle.md:8`, so a
prose-only system could pass that gate without ever reading the PNG. Measured alternative:

> "According to the January 2026 data dictionary diagram, what declared type does
> `orders.total` have?" → **`REAL (USD)`**

`REAL (USD)` occurs nowhere in prose (grep: only `apps/order-service/migrations/001-orders.sql:2`
has `total REAL NOT NULL`), and the current schema says `total_minor`
(`002-minor-units.sql:3` drops `total`). So `total_minor` proves a
prose answer, `REAL` alone proves a truncated OCR read, and only `REAL (USD)` proves the PNG was
read. Runner-up for a second test: `people-finance-process.png`, "when is the approved-leave CSV
prepared" → `Friday 16:00`, also absent from prose.

### Line style is status, not decoration

The two workshop/finance diagrams draw **dashed** edges, and `people-identity-workshop.png` carries
an in-image legend: *"Dashed arrows = discussion only"*. Emitting those as ordinary edges at 0.6
confidence would assert exactly what the diagram disclaims. So stage 2 maps style to the existing
status lattice: solid → `VALID` (still only 0.6 extraction confidence), dashed or dotted →
`PROPOSED`, arrowless → no direction, and the claim records the style. This needs no new status
and no new vocabulary.

### Stage 2 scope, bounded by what is visible

| diagram | geometry verdict | reason observed |
|---|---|---|
| `customer-orders-erd`, `architecture-january` | boxes trustworthy, connectors poor | measured: 3 and 7 hollow boxes detected correctly, but only 0 and 3 connector segments join two distinct boxes |
| `checkout-sequence`, `architecture-september` | risky | return arc parallel to the column; 8 of 12 September edges unlabelled and arriving in near-coincident clusters |
| `people-finance-process`, `people-identity-workshop` | unreliable | dashed/dotted arrowless connectors, dog-eared notes, dashed box border |

The "≥80% of arrows on a labelled sample of 3" gate must therefore name its three diagrams up
front, or it measures the choice of sample rather than the detector. Stage 2 ships only for the
first row; the rest stay text-only.

### Obligations this creates, verified against the code

A `Region` on `Span` is not a one-line addition. Each site below currently discards it, so the
claim would be stored, cited and verified *without* its rectangle — the exact failure the design is
meant to prevent:

| site | today | required |
|---|---|---|
| `models/claim.py:113-123` (`claim_id`) | hashes triple + polarity + `path:start-end` + `extractor_version` | append the region **only when present**, so the 311 existing ids stay byte-identical |
| `graph/loader.py:39-44` | MERGEs `Span {path, start_line, end_line}`, SETs only `content_hash` | add `region` to the MERGE key, else two claims on one diagram collapse into one span |
| `retrieval/cqp.py:167-169` | projects `{path, start_line, end_line, hash}` | project `region` |
| `retrieval/service.py:452-489` (`_verify`) | rebuilds citations from four keys | carry `region` through and run the four legs |

Changing `models/` needs agreement from all workstream owners (`AGENTS.md:123-125`), not one.

### `extractor_version` does not work today, so it cannot be relied on

Measured: `grep -rn extractor_version` finds only the default `"1"` in `models/claim.py:95`, its use
inside `claim_id`, and a copy in `graph/loader.py:32,74`. **No pipeline sets it** — all 284 extracted
claims carry `"1"` — and no cache uses it. Worse, nothing deletes claims: `graph/loader.py` has no
`DELETE`, so bumping the version would **duplicate** diagram claims beside the old ones instead of
invalidating them, and `docs/08`'s rollback ("deleting its claims") has no code path.

Stage 1 therefore requires, before OCR claims are written:
1. each pipeline sets `extractor_version` from its own inputs (for OCR: engine version, tessdata
   SHA-256, `psm`, `oem`, `lang`, plus our reading-order revision);
2. a version-scoped delete before load, so a re-extract replaces rather than duplicates;
3. a documented invariant: a mismatch between a claim's version and the running extractor means the
   claim is stale, not merely old.

### Documents that must change in the same commit as the code

`docs/05-extraction-pipelines.md:49,54,172-196` already describes a PNG route and a two-stage VLM
design that this ADR replaces; `docs/03-ontology.md:151` cites a "VLM-extracted" authority;
`docs/06-retrieval.md:116,243` states the citation shape; `docs/07-api-and-mcp.md:74` documents
`/v1/span` as the literal bytes behind a citation, which for an image is a rectangle, not a line
range. Leaving them is the drift that `AGENTS.md:178-179` forbids.

## Consequences

- One apt language-data package and one wheel enter the image for stage 1 (+43 MB); stage 2's
  +217 MB and its LGPL FFmpeg are deferred until stage 1 proves it cannot answer the questions
  that matter. That budget is the reason this ADR is Proposed.
- Diagram text becomes searchable in the same layer as prose (`evidence`), so the expensive
  part — the retrieval path — needs no change at all.
- The geometry stage will be wrong on some diagrams, confidently and silently. Mitigation is
  the labelled-sample gate in the table above, not hope.
- If stage 1 alone answers the questions that matter, stages 2–3 are cancelled, and the ADR is
  amended to say so.
