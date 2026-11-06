# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Gate 2 — the span gate (docs/03-ontology.md). The excerpt is a hint; the file at
its hash is the judge. Not found anywhere → dropped, never repaired."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from models.claim import EvidenceHint, Span


class SourceUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Source:
    lines: list[str]
    content_hash: str


def read_source(corpus_root: Path, transcripts_dir: Path, path: str) -> Source:
    """A PNG cannot be quoted, so its lines and hash are those of the human-reviewed
    transcription committed under data/fixtures/diagrams/."""
    if path.endswith(".png"):
        file = transcripts_dir / f"{PurePosixPath(path).stem}.json"
        if not file.is_file():
            raise SourceUnavailable(f"no reviewed transcription for {path}")
        raw = file.read_bytes()
        data = json.loads(raw)
        if data.get("source") != path:
            raise SourceUnavailable(f"{file.name} transcribes {data.get('source')}, not {path}")
        return Source(list(data["lines"]), hashlib.sha256(raw).hexdigest())

    file = (corpus_root / path).resolve()
    if not file.is_relative_to(corpus_root.resolve()) or not file.is_file():
        raise SourceUnavailable(f"{path} does not exist in the corpus")
    raw = file.read_bytes()
    return Source(raw.decode("utf-8").splitlines(), hashlib.sha256(raw).hexdigest())


def _found_at(excerpt: str, lines: list[str], start: int) -> bool:
    height = excerpt.count("\n") + 1
    return excerpt in "\n".join(lines[start - 1 : start - 1 + height])


def locate(hint: EvidenceHint, source: Source) -> tuple[Span, bool] | None:
    """(span, corrected) — corrected when the excerpt was found off the hinted line.
    end_line is derived from the excerpt, never taken from the extractor."""
    height = hint.excerpt.count("\n")
    starts = [hint.start_line, *range(1, len(source.lines) + 1)]
    for start in starts:
        if start <= len(source.lines) and _found_at(hint.excerpt, source.lines, start):
            span = Span(
                path=hint.path,
                start_line=start,
                end_line=start + height,
                content_hash=source.content_hash,
            )
            return span, start != hint.start_line
    return None
