"""Opt-in capabilities: a pipeline whose dependency the operator must approve.

A pipeline may need something the default install deliberately does not carry — a
copyleft library that would otherwise spread over the whole work, a model download, a
native binary. Declaring it here buys three properties:

- **The default build stays clean.** Nothing copyleft is imported, and declining is not
  an error: the skipped capability produces exactly the output of a build where it was
  never installed.
- **Consent is asked once, up front, with the facts.** When the walk finds files that
  would go through the module, the operator sees the count, the licence and the cost
  before any work happens, and answers y/N.
- **A non-interactive run never blocks.** No TTY and no flag means skip-and-report, so
  a corpus sweep can run unattended without silently agreeing on the operator's behalf.

File division is the other half of the licence rule and lives in packaging, not here:
everything GPL-dependent sits in its own module and its own `pyproject` extra, and is
imported lazily inside `extract()` so that importing the pipeline never imports it.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

# Consent is never assumed: an empty answer, EOF, or a keypress that is neither y nor
# yes all mean no.
ACCEPT_WORDS = frozenset({"y", "yes"})


@dataclass(frozen=True)
class OptIn:
    """One capability the user must agree to before it runs."""

    name: str  # the token passed to --accept-opt-in
    licence: str  # the copyleft part that forces the opt-in, named exactly
    why: str  # one line: what it buys and what it costs to enable
    modules: tuple[str, ...] = ()  # importable names that must resolve
    extra: str = ""  # pip extra that installs them
    dev_only: bool = False

    def state(self) -> tuple[bool, str]:
        """Installed? A module that is absent is a fact, not a choice: do not ask."""
        missing = [name for name in self.modules if importlib.util.find_spec(name) is None]
        if not missing:
            return True, "installed"
        hint = f"; pip install -e '.[{self.extra}]'" if self.extra else ""
        return False, f"not installed ({', '.join(missing)}){hint}"


def human_assist_allowed(files: int, *, limit: int | None = None) -> tuple[bool, str]:
    """A person may review only a handful of files; above the ceiling the automatic
    route is the only option (settings.HUMAN_ASSIST_MAX_FILES)."""
    from settings import HUMAN_ASSIST_MAX_FILES

    ceiling = HUMAN_ASSIST_MAX_FILES if limit is None else limit
    if files > ceiling:
        return False, f"{files} files exceeds the {ceiling}-file assist ceiling; use the automatic route"
    return True, f"{files} files within the {ceiling}-file assist ceiling"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def agree(
    opt_in: OptIn,
    *,
    files: int,
    accepted: frozenset[str] = frozenset(),
    rejected: frozenset[str] = frozenset(),
    ask: Callable[[str], str] | None = None,
    stream: TextIO = sys.stderr,
) -> Decision:
    """Decide one capability: flag, or an explicit answer, or nothing.

    Order matters. An explicit refusal always wins, so a deployment can pin a module off
    even when its extra happens to be installed. Then the flag, which is what an
    unattended run uses. Only then a prompt, and only if the caller supplied one.
    """
    if opt_in.name in rejected:
        return Decision(False, "--decline-opt-in")
    installed, state = opt_in.state()
    if not installed:
        return Decision(False, state)
    if opt_in.name in accepted:
        return Decision(True, "--accept-opt-in")
    if ask is None:
        return Decision(False, f"needs --accept-opt-in {opt_in.name} (non-interactive)")

    print(
        f"opt-in {opt_in.name}: {files} file(s) would be extracted\n"
        f"  licence: {opt_in.licence}\n"
        f"  {opt_in.why}",
        file=stream,
    )
    answer = ask(f"  enable {opt_in.name}? [y/N] ").strip().lower()
    return Decision(answer in ACCEPT_WORDS, f"answered {answer or 'nothing'!r}")
