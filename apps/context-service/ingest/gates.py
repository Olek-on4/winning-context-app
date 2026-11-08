"""Gate 2 and dating-by-reference, both streaming.

A pipeline may know *what* a document says without knowing *where*: the model returns an
excerpt and a guessed line. `locate` turns that guess into a verified span or nothing,
and `verify` applies it to a batch on the way into the graph (issue 73).
`dated_by_reference` dates an undated artefact by the record that ships it, because git
stamps every corpus file with the same day.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from models.claim import ClaimRecord, Span
from sources import Root, SpanStore, image_size

GATE_WINDOW = 2  # lines a verified claim may drift; a larger move is a different location


@dataclass(frozen=True)
class GateCounts:
    """What the span gate did, reported on every load (docs/09)."""

    kept: int = 0
    dropped: int = 0
    relocated: int = 0
    ungeated: int = 0

    @property
    def pass_rate(self) -> float | None:
        """Share of gated claims that survived; None when nothing carried an excerpt."""
        gated = self.kept + self.dropped
        return None if gated == 0 else round(self.kept / gated, 4)

    def as_json(self) -> dict[str, int | float | None]:
        return {
            "kept": self.kept,
            "dropped": self.dropped,
            "relocated": self.relocated,
            "ungeated": self.ungeated,
            "pass_rate": self.pass_rate,
        }


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


def verify(
    claims: Iterable[ClaimRecord], store: SpanStore, window: int = GATE_WINDOW
) -> tuple[list[ClaimRecord], GateCounts]:
    """Resolve every excerpt against the cited file; drop what the bytes do not prove.

    Only a window around the cited line is read, so a moved excerpt is found cheaply and
    a claim whose text is gone is dropped with its reason on stderr. A claim with no
    excerpt has nothing to verify yet still loads: fixtures are pointer-only by design.
    """
    kept: list[ClaimRecord] = []
    gated = relocated = dropped = ungeated = 0
    for claim in claims:
        excerpt = claim.excerpt
        span = claim.evidence[0]
        if span.region is not None:
            # An image has no verbatim text to find. The region is verified geometrically:
            # inside the real dimensions, and against the bytes that were indexed.
            gated += 1
            if excerpt:
                print(
                    f"span-gate: dropped {claim.claim_id} {span.path}: a region claim quotes no text",
                    file=sys.stderr,
                )
                dropped += 1
                continue
            problem = _region_problem(span, store)
            if problem:
                print(f"span-gate: dropped {claim.claim_id} {span.path}@{span.region}: {problem}", file=sys.stderr)
                dropped += 1
                continue
            kept.append(claim)
            continue
        if not excerpt:
            ungeated += 1
            kept.append(claim)
            continue
        start = max(1, span.start_line - window)
        end = span.end_line + window
        gated += 1
        try:
            block = store.read(span.path, start, end).decode("utf-8", errors="replace").splitlines()
        except (OSError, ValueError) as error:
            # Unresolvable pointer or unreadable file: the gate cannot vouch for the claim.
            print(f"span-gate: dropped {claim.claim_id} {span.path}:{span.start_line}: {error}", file=sys.stderr)
            dropped += 1
            continue
        found = locate(block, excerpt, hint=span.start_line - start + 1)
        if found is None:
            print(
                f"span-gate: dropped {claim.claim_id} {span.path}: excerpt not found verbatim in {start}-{end}",
                file=sys.stderr,
            )
            dropped += 1
            continue
        found_start, found_end, _ = found
        absolute_start = start + found_start - 1
        absolute_end = start + found_end - 1
        if absolute_start != span.start_line:
            relocated += 1
        if (absolute_start, absolute_end) != (span.start_line, span.end_line):
            # end_line is derived from the excerpt, never trusted from the extractor.
            claim = claim.model_copy(update={"evidence": [
                span.model_copy(update={"start_line": absolute_start, "end_line": absolute_end}),
                *claim.evidence[1:],
            ]})
        kept.append(claim)
    return kept, GateCounts(kept=gated - dropped, dropped=dropped, relocated=relocated, ungeated=ungeated)


def _region_problem(span: Span, store: SpanStore) -> str | None:
    """What disqualifies a rectangle, or None. Bounds then bytes, in that order."""
    try:
        path = store.resolve(span.path)
        width, height = image_size(path)
    except (OSError, ValueError) as error:
        return str(error)
    assert span.region is not None
    if span.region.x + span.region.w > width or span.region.y + span.region.h > height:
        return f"region {span.region} escapes the {width}x{height} image"
    if store.hash(span.path) != span.content_hash:
        return "file bytes changed since the rectangle was read"
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
