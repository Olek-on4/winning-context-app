"""Compatibility surface: deterministic extraction now lives in `ingest.registry`.

Kept so callers (tests, CLI) do not have to know when the pipeline architecture moved.
Pass a `Root` for one tree, or a path and it is discovered as a root.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from ingest.registry import PIPELINES, register, route
from ingest.registry import extract as extract_root
from sources import Root, discover

__all__ = ["PIPELINES", "extract", "register", "route"]


def extract(
    root: Root | Path,
    *,
    accepted: frozenset[str] = frozenset(),
    rejected: frozenset[str] = frozenset(),
    ask: Callable[[str], str] | None = None,
    stream: TextIO = sys.stderr,
    record: dict[str, str] | None = None,
) -> list:
    """Extract claims from any directory; nothing about the data is assumed.

    `accepted`/`rejected`/`ask` are forwarded to the opt-in gate, so a caller decides
    whether a copyleft capability may run (ingest/optin.py).
    """
    options = dict(accepted=accepted, rejected=rejected, ask=ask, stream=stream, record=record)
    if isinstance(root, Root):
        return extract_root(root, **options)
    roots = discover([Path(root)])
    return [claim for discovered in roots for claim in extract_root(discovered, **options)]
