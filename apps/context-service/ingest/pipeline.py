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
from ingest.gates import Source, SourceUnavailable, locate, read_source
from ingest.headers import capped_modality, declared_status
from ingest.router import source_type
from models.claim import ClaimRecord, EvidenceHint, ExtractedClaim, Span
from models.ontology import TimeSignal
from settings import Settings

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    written: int = 0
    span_corrected: int = 0
    modality_capped: int = 0
    dropped: list[str] = field(default_factory=list)


class _Sources:
    def __init__(self, settings: Settings) -> None:
        self._corpus = settings.corpus_root
        self._transcripts = settings.resolve_path(settings.diagram_transcripts_dir)
        self._cache: dict[str, Source] = {}

    def __call__(self, path: str) -> Source:
        if path not in self._cache:
            self._cache[path] = read_source(self._corpus, self._transcripts, path)
        return self._cache[path]


def _verify(hint: EvidenceHint, sources: _Sources, report: IngestReport) -> Span:
    try:
        source = sources(hint.path)
    except SourceUnavailable as exc:
        raise ValueError(str(exc)) from exc
    found = locate(hint, source)
    if found is None:
        raise ValueError(f"excerpt not found in {hint.path} (hinted line {hint.start_line})")
    span, corrected = found
    report.span_corrected += corrected
    return span


def _date(primary: Span, time_span: Span | None, sources: _Sources, cfg: Settings) -> Dated | None:
    if dated := date_from_content(primary.path, sources(primary.path).lines):
        return dated
    if time_span and (ref := date_from_content(time_span.path, sources(time_span.path).lines)):
        return Dated(ref.on, ref.precision, TimeSignal.REFERENCED_RECORD)
    if primary.path.endswith(".png"):
        return None
    return date_from_git(cfg.corpus_root, primary.path)


def claim_id(claim: ExtractedClaim, spans: list[Span]) -> str:
    """hash(subject, predicate, object, span, extractor_version) — re-runs MERGE."""
    core = claim.model_dump(mode="json", exclude={"evidence", "time_evidence"})
    core["evidence"] = [s.model_dump(mode="json") for s in spans]
    canonical = json.dumps(core, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def to_record(
    claim: ExtractedClaim, sources: _Sources, cfg: Settings, report: IngestReport
) -> ClaimRecord:
    spans = [_verify(h, sources, report) for h in claim.evidence]
    time_span = _verify(claim.time_evidence, sources, report) if claim.time_evidence else None
    dated = _date(spans[0], time_span, sources, cfg)
    status = declared_status(sources(spans[0].path).lines)
    modality = capped_modality(claim.modality, status, cfg)
    report.modality_capped += modality is not claim.modality
    return ClaimRecord(
        **claim.model_dump(exclude={"evidence", "time_evidence", "modality"}),
        modality=modality,
        modality_capped_from=claim.modality if modality is not claim.modality else None,
        declared_status=status,
        id=claim_id(claim, spans),
        evidence=spans,
        time_evidence=time_span,
        source_type=source_type(spans[0].path),
        observed_at=dated.on if dated else None,
        observed_precision=dated.precision if dated else None,
        time_signal=dated.signal if dated else None,
        valid_from=dated.on if dated else None,
        valid_from_precision=dated.precision if dated else None,
    )


def ingest(cfg: Settings, source: Path | None = None) -> IngestReport:
    source = source or cfg.resolve_path(cfg.fixtures_path)
    target = cfg.resolve_path(cfg.claims_path)
    sources = _Sources(cfg)
    report = IngestReport()
    records: dict[str, ClaimRecord] = {}

    for number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = to_record(ExtractedClaim.model_validate_json(raw), sources, cfg, report)
        except (ValidationError, ValueError) as exc:
            reason = f"{source.name}:{number}: {exc}".replace("\n", " ")
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
