# 0011 — The envelope carries evidence, not only claims

Status: Accepted (extends [0010](0010-semantic-claims-and-effort.md))

## Context

284 claims were extracted from 897 chunks: roughly two thirds of the corpus never became a
claim. Retrieval still found those chunks — the embeddings and BM25 both worked — but the
answer surface had nowhere to put them, so they were rendered as a sentence in `gaps`:
*"No claims matched; evidence candidates were a.md, b.md, c.md"*. A caller could not cite,
render or traverse them, and a question the corpus answers in prose looked unanswerable.

Two ways to close it:

1. **Promote chunks to claims.** Breaks the contract the product rests on: a claim is a
   triple with a status, a validity window and a span-verified citation; a chunk is text
   that merely matched.
2. **Add a second, honestly labelled layer.** Claims stay claims; passages are returned as
   `evidence` with path, line range, heading, hash and the channel that found them — and
   never a status, because "the corpus says this here" is not "this is true".

## Decision

Option 2. `evidence` is a new envelope field; `claims` is untouched.

- A passage must pass the **same verification as a citation**: the file hash and the line
  range are checked against the real file. A chunk whose hash does not match is dropped.
- A passage must be **corroborated**: a shared content word, or agreement between both
  channels. Meaning alone is rejected, because measured chunk cosine puts signal and noise
  in the same 0.75–0.79 band.
- A passage must **look like prose** (`EVIDENCE_MIN_CHARS`, `EVIDENCE_MIN_RATIO`). Measured:
  without this, `"what cases are we covering"` returned `}` from `pnpm-lock.yaml` as its
  top hit. The rule measures the shape of the text, not a list of file names.
- Count is bounded by effort (2/3/5/8 for levels 1–4), so the envelope stays readable and
  a vague question cannot flood the answer with noise.
- `heading_path` is carried so a client can group passages by section — the coarse layer
  above passages. Reading the wrong property name (`heading`) had silently emptied it.

## Consequences

- A question that matches no claim now returns cited prose instead of a sentence about
  files. Measured: `"how does the console handle exceptions"` returns the console-exception
  meeting note at `meeting-notes/2026-07-16-console-exception.md:1-9`.
- The envelope changed, so every consumer was updated in the same commit: the REST response,
  the MCP tools that return it verbatim, and the tests that assert its exact key set.
- Classifying "nothing matched" versus "a channel broke" stays separate: an index holding no
  vectors is still `degraded` (#79), and the gap text names the channel.
- A passage is not ranked against a claim. Both layers are returned together; how to weight
  cited prose against a statused claim is the caller's judgement, and pretending otherwise
  would mean inventing a score that means nothing.
