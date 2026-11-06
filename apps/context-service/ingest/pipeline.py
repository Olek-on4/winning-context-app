# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Extracted claims → gate 1 (schema) → gate 2 (span) → dating → claims.jsonl."""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from ingest.dates import Dated, date_from_content, date_from_git
from ingest.gates import SourceUnavailable, read_lines, span_failure
from ingest.router import source_type
from models.claim import ClaimRecord, ExtractedClaim, Span
from models.ontology import TimeSignal
from settings import Settings

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    written: int = 0
    dropped: list[str] = field(default_factory=list)


def claim_id(claim: ExtractedClaim) -> str:
    """Content-derived, so a re-run MERGEs instead of duplicating."""
    canonical = json.dumps(claim.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class _Lines:
    def __init__(self, settings: Settings) -> None:
        self._corpus = settings.corpus_root
        self._transcripts = settings.resolve_path(settings.diagram_transcripts_dir)
        self._cache: dict[str, list[str]] = {}

    def __call__(self, path: str) -> list[str]:
        if path not in self._cache:
            self._cache[path] = read_lines(self._corpus, self._transcripts, path)
        return self._cache[path]


def _checked(span: Span, lines: _Lines) -> list[str]:
    """Return the file's lines, or raise ValueError naming the broken span."""
    try:
        file_lines = lines(span.path)
    except SourceUnavailable as exc:
        raise ValueError(str(exc)) from exc
    if reason := span_failure(span, file_lines):
        raise ValueError(reason)
    return file_lines


def _date(claim: ExtractedClaim, lines: _Lines, settings: Settings) -> Dated | None:
    primary = claim.evidence[0]
    if dated := date_from_content(primary.path, lines(primary.path)):
        return dated
    if claim.time_evidence is not None:
        te = claim.time_evidence
        if referenced := date_from_content(te.path, _checked(te, lines)):
            return Dated(referenced.on, referenced.precision, TimeSignal.REFERENCED_RECORD)
    if primary.path.endswith(".png"):
        return None
    return date_from_git(settings.corpus_root, primary.path)


def to_record(claim: ExtractedClaim, lines: _Lines, settings: Settings) -> ClaimRecord:
    for span in claim.evidence:
        _checked(span, lines)
    dated = _date(claim, lines, settings)
    return ClaimRecord(
        **claim.model_dump(),
        id=claim_id(claim),
        source_type=source_type(claim.evidence[0].path),
        observed_at=dated.on if dated else None,
        observed_precision=dated.precision if dated else None,
        time_signal=dated.signal if dated else None,
        valid_from=dated.on if dated else None,
        valid_from_precision=dated.precision if dated else None,
    )


def ingest(settings: Settings, source: Path | None = None) -> IngestReport:
    source = source or settings.resolve_path(settings.fixtures_path)
    target = settings.resolve_path(settings.claims_path)
    lines = _Lines(settings)
    report = IngestReport()
    records: dict[str, ClaimRecord] = {}

    for number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        where = f"{source.name}:{number}"
        try:
            record = to_record(ExtractedClaim.model_validate_json(raw), lines, settings)
        except (ValidationError, ValueError) as exc:
            reason = f"{where}: {exc}".replace("\n", " ")
            log.warning("dropped claim %s", reason)
            report.dropped.append(reason)
            continue
        records[record.id] = record

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as out:
        for key in sorted(records):
            out.write(records[key].model_dump_json() + "\n")
    report.written = len(records)
    return report
