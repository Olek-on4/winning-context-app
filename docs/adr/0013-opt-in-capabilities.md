# ADR-0013 — Opt-in capabilities and the licence boundary

Status: Accepted

## Context

Some extraction capability needs something the default install should not carry: a
library whose licence is stronger than MPL-2.0, a multi-gigabyte model, a native binary.
The trigger was concrete — text recognition of diagram images pulls `libjbig0`
(**GPL-2.0-or-later**) through `libleptonica`, and the geometry route pulls LGPL-2.1
FFmpeg inside `opencv-python-headless`. The work must remain usable, and redistributable
under its own terms, without those components.

Two failure modes have to be prevented, and they pull in opposite directions:

- **Silent agreement.** A batch sweep that installs the extra and never says so has
  effectively relicensed the deployment without the operator deciding.
- **Silent absence.** A capability that is skipped because a dependency is missing looks
  exactly like a corpus that contains nothing to extract — the "zero claims" trap this
  project already treats as a defect.

## Options

1. **Link it and document the licence.** One image, one licence file, notices shipped.
   Cheapest, and defensible for mere aggregation of unmodified libraries — but it makes
   the GPL part unavoidable for anyone who only wants the text pipelines, and "we
   documented it" is not a boundary a downstream user can act on.
2. **A separate container or service.** Cleanest legal separation, and the most
   infrastructure: a second deployable, a transport, a failure mode, an operational
   story. For a capability used on six files this is worse than the disease.
3. **An opt-in module with a consent gate.** The dependency lives in its own module and
   its own packaging extra; the import is lazy; the walk announces what it found and what
   the licence is, and asks before running. Declining changes nothing else.
4. **Do nothing.** Diagram text stays unreadable to the service, and the corpus's own
   README statement ("a drawn connection can be useful evidence") goes unanswered.

## Decision

Option 3, implemented once in `apps/context-service/ingest/optin.py` and used by every
optional capability, not just images:

```python
opt_in = OptIn(name="diagram-ocr", licence="GPL-2.0-or-later (libjbig via libleptonica)",
               why="diagram text and geometry; +43 MB image, GPL contained to one module",
               modules=("tesserocr",), extra="diagram-tesseract")
```

- **Declared, not inferred.** The pipeline names the licence of the copyleft part exactly.
- **Discovery stays honest.** `iter_files(claimable=...)` yields files a gated pipeline
  matches even when they are not text, so the count shown is the real one over the whole
  corpus rather than the text subset. Without this the gate is exercised only by tests and
  never by the images it exists for.
- **Asked once, before work.** `N file(s) would be extracted`, the licence, the cost, then
  `enable <name>? [y/N]`. Only `y`/`yes` mean yes; empty, `n`, or anything else means no.
- **Unattended is explicit.** `--accept-opt-in NAME` accepts; `--decline-opt-in NAME`
  refuses and always wins over acceptance; no TTY and no flag means skip and name the flag,
  never assume. `ETYT_ACCEPT_OPT_IN` exists for compose.
- **The install line is real.** Extras are declared in `pyproject.toml`
  (`diagram`, `diagram-tesseract`); the default `dependencies` list does not grow.
- **A ceiling on human assist.** `human_assist_allowed(files)` refuses review above
  `settings.HUMAN_ASSIST_MAX_FILES` (20), so a corpus of thousands can never be worked
  through by hand one file at a time.
- **A missing module is a fact, not a question.** An uninstalled dependency is reported
  with the install line and is never prompted for.
- **Declining is byte-identical** to a build without the module, and every skipped file is
  named on stderr so the gap is auditable.

File division follows the same rule: the gated module is its own file, listed under its own
`pyproject` extra, imports its dependency inside `extract()` rather than at import, and no
ungated module may import it.

## Consequences

- The default install stays MPL-clean and does not grow by the copyleft component's size.
- One mechanism serves every future capability (a model download, a native binary, a
  paying API), so adding one means adding an `OptIn` — no edits to the walker or the CLI.
- Extra interaction in an interactive run: the operator answers a question once per
  capability. In CI, one flag per run.
- The gate cannot know whether the *user* of a corpus is entitled to a licence; it records
  that the operator accepted, and prints the licence so the decision is informed.
- A module that needs the capability programmatically (a test, another service) must pass
  `accepted=` explicitly — deliberate: there is no ambient "already agreed" state.
