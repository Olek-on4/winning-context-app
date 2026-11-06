"""Gate 2 and dating-by-reference, both streaming.

A pipeline may know *what* a document says without knowing *where*: the model returns an
excerpt and a guessed line. `locate` turns that guess into a verified span or nothing.
`dated_by_reference` dates an undated artefact by the record that ships it, because git
stamps every corpus file with the same day.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from sources import Root


def locate(lines: list[str], excerpt: str, hint: int | None = None) -> tuple[int, int, bool] | None:
    """Find `excerpt` verbatim and return (start, end, corrected).

    Exact hit at the hint → `corrected=False`. Found elsewhere in the file → the real
    lines, `corrected=True`. Absent → `None`, and the caller drops the claim; a span is
    never repaired by guesswork.
    """
    wanted = excerpt.strip()
    if not wanted:
        return None
    span = wanted.count("\n") + 1
    for start, line in enumerate(lines, start=1):
        if line.strip() != wanted.splitlines()[0].strip():
            continue
        block = lines[start - 1 : start - 1 + span]
        if "\n".join(part.rstrip("\n") for part in block).strip() == wanted:
            return start, start + span - 1, hint is not None and start != hint
    return None


_ARTIFACT = re.compile(r"[\w./-]+\.(?:sql|yaml|yml|json|png|md)")


def dated_by_reference(root: Root, artifact: str) -> date | None:
    """Date an undated file from the release that names it.

    Streams each release, so a large tree costs one pass per candidate, not one copy.
    """
    wanted = Path(artifact).name
    # Releases name migrations by number ("migration 002"), not by file name.
    number = re.match(r"(\d{3,})", wanted)
    pattern = (
        re.compile(rf"migration\s+{number.group(1)}\b|\b{number.group(1)}-[\w-]+\.sql\b", re.IGNORECASE)
        if number
        else re.compile(re.escape(wanted))
    )
    releases = sorted((root.path / "releases").glob("*.md")) if (root.path / "releases").is_dir() else []
    for release in releases:
        named = pattern.search(release.read_text(encoding="utf-8", errors="replace"))
        if not named:
            continue
        match = re.search(r"(\d{4})-(\d{2})(?:-(\d{2}))?", release.name)
        if match:
            year, month, day = match.groups()
            return date(int(year), int(month), int(day or 1))
    return None


def references(root: Root) -> Iterable[tuple[str, date]]:
    """(artifact name, date) for every release that names a file — small, cached by caller."""
    for release in sorted((root.path / "releases").glob("*.md")) if (root.path / "releases").is_dir() else []:
        match = re.search(r"(\d{4})-(\d{2})(?:-(\d{2}))?", release.name)
        if not match:
            continue
        year, month, day = match.groups()
        stamp = date(int(year), int(month), int(day or 1))
        for artifact in _ARTIFACT.findall(release.read_text(encoding="utf-8", errors="replace")):
            yield Path(artifact).name, stamp
