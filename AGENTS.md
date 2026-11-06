# AGENTS.md

Project rules for `winning-context-app`. Global rules in `~/.agents/AGENTS.md` still apply; this file only adds project-local constraints.

## What this project is

A Context Service over the AT&T "Northstar Equipment" corpus. The service ingests the corpus, extracts entities and evidence, and answers context queries with citations back to source files. Goal is an evidence-backed answer, not a plausible one: every claim returned must point at a corpus file and line.

## Hard invariants

1. **Corpus is read-only input.** `vendor/att-hackathon-task` is a git submodule. NEVER edit files inside it, NEVER commit submodule pointer changes unless the task is explicitly "bump corpus". Report corpus defects upstream instead.
2. **Corpus is fictional.** All people, incidents, and records in it are invented. Never treat corpus content as real external facts, and never copy it into our docs as truth without citing the file.
3. **No derived data in git.** Parsed corpus dumps, embeddings, vector stores, `*.sqlite`, `*.duckdb`, indexes go to `data/local/` or `indexes/` (gitignored).
4. **Citations are structural.** Point at the corpus path plus line/range, e.g. `vendor/att-hackathon-task/docs/adr/0007-*.md:12-30`. Never cite by title alone, and never invent a path — verify it exists.
5. **License**: MPL-2.0 for our files. New source files carry the Exhibit A notice header where the language supports comments.

## Layout

- `apps/` — implementation code. One app per deployable; no cross-app imports.
- `docs/` — our design notes, ADRs, API contracts.
- `vendor/att-hackathon-task` — corpus submodule.

## Workflow

- Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`. One logical change per commit.
- GROUND -> PLAN -> ACT -> VERIFY. Any claim about corpus structure must come from reading the corpus, not from the upstream README.
- Verification must be executable: run the ingester, query the service, show output. "Looks correct" is not verification.
- Adding a dependency or switching the implementation language: ask first.

## Commands

Not defined yet. When the first app lands, replace this section with the real, tested commands (install, ingest, serve, test) and keep it current.
