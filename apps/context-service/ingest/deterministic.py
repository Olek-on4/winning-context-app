"""Compatibility surface: deterministic extraction now lives in `ingest.registry`.

Kept so callers (tests, CLI) do not have to know when the pipeline architecture moved.
Pass a `Root` for one tree, or a path and it is discovered as a root.
"""

from __future__ import annotations

from pathlib import Path

from ingest.registry import PIPELINES, register, route
from ingest.registry import extract as extract_root
from sources import Root, discover

__all__ = ["PIPELINES", "extract", "register", "route"]


def extract(root: Root | Path) -> list:
    """Extract claims from any directory; nothing about the data is assumed."""
    if isinstance(root, Root):
        return extract_root(root)
    roots = discover([Path(root)])
    return [claim for discovered in roots for claim in extract_root(discovered)]
