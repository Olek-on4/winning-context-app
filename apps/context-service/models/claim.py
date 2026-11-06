# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""ClaimRecord — the one envelope every pipeline emits (docs/05-extraction-pipelines.md)."""

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.ontology import (
    DocStatus,
    EntityKind,
    Modality,
    Polarity,
    Precision,
    Predicate,
    SourceType,
    Status,
    TimeSignal,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class EntityRef(BaseModel):
    model_config = _FROZEN
    kind: EntityKind
    key: str = Field(min_length=1)


def _relative(path: str) -> str:
    if path.startswith("/") or ".." in path.split("/"):
        raise ValueError("path must be relative to the corpus root")
    return path


class EvidenceHint(BaseModel):
    """Extractor output for gate 2: where it thinks the text is. Never persisted."""

    model_config = _FROZEN
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    excerpt: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        _relative(self.path)
        return self


class Span(BaseModel):
    """A verified pointer. For a diagram, lines index the reviewed transcription in
    data/fixtures/diagrams/<stem>.json and the hash is that file's."""

    model_config = _FROZEN
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> Self:
        _relative(self.path)
        if self.end_line < self.start_line:
            raise ValueError("end_line before start_line")
        return self


class _ClaimCore(BaseModel):
    model_config = _FROZEN
    subject: EntityRef
    predicate: Predicate
    object: EntityRef
    polarity: Polarity
    modality: Modality
    confidence: float = Field(ge=0.0, le=1.0)
    extractor: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)


class ExtractedClaim(_ClaimCore):
    """What a pipeline (or a reviewed fixture) produces, before gate 2 and dating.

    `time_evidence` dates a file with no date of its own (SQL, config): a hint into the
    record that does, e.g. the release note that shipped a migration."""

    evidence: list[EvidenceHint] = Field(min_length=1)
    time_evidence: EvidenceHint | None = None


class ClaimRecord(_ClaimCore):
    """A claim that passed the gates and was dated by ingest."""

    id: str
    evidence: list[Span] = Field(min_length=1)
    time_evidence: Span | None
    source_type: SourceType
    declared_status: DocStatus | None
    modality_capped_from: Modality | None
    observed_at: date | None
    observed_precision: Precision | None
    time_signal: TimeSignal | None
    valid_from: date | None
    valid_from_precision: Precision | None


class ScoreBreakdown(BaseModel):
    model_config = _FROZEN
    authority: float
    time_confidence: float
    extractor_confidence: float
    settledness: float
    freshness: float
    score: float


class ResolvedClaim(BaseModel):
    """A claim after the temporal resolver: status, closed validity, and why."""

    model_config = _FROZEN
    claim: ClaimRecord
    status: Status
    reason: str
    valid_to: date | None
    valid_to_precision: Precision | None
    score: ScoreBreakdown
    confidence: float = Field(ge=0.0, le=1.0)
    superseded_by: list[str] = []
    conflicts_with: list[str] = []
    corroborated_by: list[str] = []
    blocked_by: list[str] = []
