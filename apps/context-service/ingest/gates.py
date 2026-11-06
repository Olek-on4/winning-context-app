# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Gate 2 — the span gate. An excerpt that is not verbatim at its cited lines is
dropped, never repaired (AGENTS.md invariant 7)."""

import json
from pathlib import Path, PurePosixPath

from models.claim import Span


class SourceUnavailable(Exception):
    pass


def read_lines(corpus_root: Path, transcripts_dir: Path, path: str) -> list[str]:
    """Text files are read from the corpus. A PNG cannot be quoted, so its lines
    come from the human-reviewed transcription committed under data/fixtures."""
    if path.endswith(".png"):
        transcript = transcripts_dir / f"{PurePosixPath(path).stem}.json"
        if not transcript.is_file():
            raise SourceUnavailable(f"no reviewed transcription for {path}")
        data = json.loads(transcript.read_text(encoding="utf-8"))
        if data.get("source") != path:
            raise SourceUnavailable(f"{transcript} transcribes {data.get('source')}, not {path}")
        return list(data["lines"])

    file = corpus_root / path
    if not file.is_file():
        raise SourceUnavailable(f"{path} does not exist in the corpus")
    return file.read_text(encoding="utf-8").splitlines()


def span_failure(span: Span, lines: list[str]) -> str | None:
    """None when the span is honest; otherwise the reason it is not."""
    if span.end_line > len(lines):
        return f"lines {span.start_line}-{span.end_line} beyond end of file ({len(lines)})"
    cited = "\n".join(lines[span.start_line - 1 : span.end_line])
    if span.excerpt not in cited:
        return f"excerpt not verbatim at {span.path}:{span.start_line}-{span.end_line}"
    return None
