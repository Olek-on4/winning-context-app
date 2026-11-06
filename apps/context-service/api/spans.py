"""Resolve a citation pointer against the corpus.

The graph stores pointers, never prose; this is the one place that turns a
(path, lines) pair back into bytes, and it refuses to leave the corpus root.
"""

from __future__ import annotations

from pathlib import Path


def read_span(root: Path, rel_path: str, start: int, end: int) -> bytes:
    """Return lines [start, end], 1-indexed and inclusive, with their own terminators."""
    if start < 1 or end < start:
        raise ValueError("start must be >= 1 and end must be >= start")
    # realpath before the containment check, so a symlink cannot smuggle the read out.
    try:
        target = (root / rel_path).resolve(strict=True)
    except (OSError, RuntimeError):
        raise FileNotFoundError(rel_path) from None
    if not target.is_relative_to(root):
        raise PermissionError(rel_path)
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    lines = target.read_bytes().splitlines(keepends=True)
    if start > len(lines) or end > len(lines):
        raise ValueError(f"range {start}-{end} is past the end of {rel_path} ({len(lines)} lines)")
    return b"".join(lines[start - 1 : end])
