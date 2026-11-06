# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""ClaimRecord — the one envelope every pipeline emits (docs/05-extraction-pipelines.md)."""

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.ontology import (
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


class Span(BaseModel):
    """Path is relative to the corpus root. For a diagram, the lines index the
    reviewed transcription in data/fixtures/diagrams/<stem>.json."""

    model_config = _FROZEN
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    excerpt: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line before start_line")
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("path must be relative to the corpus root")
        return self


class ExtractedClaim(BaseModel):
    """What a pipeline (or a reviewed fixture) produces, before dating and ids.

    `time_evidence` is for files with no intrinsic date (code, SQL): a span in another
    record that dates them, e.g. the release note that shipped a migration."""

    model_config = _FROZEN
    subject: EntityRef
    predicate: Predicate
    object: EntityRef
    polarity: Polarity
    modality: Modality
    evidence: list[Span] = Field(min_length=1)
    time_evidence: Span | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    extractor: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)


class ClaimRecord(ExtractedClaim):
    """An ExtractedClaim that passed the gates and was dated by ingest."""

    id: str
    source_type: SourceType
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
    freshness: float
    score: float


class ResolvedClaim(BaseModel):
    """A claim after the temporal resolver: status, closed validity, and why."""

    model_config = _FROZEN
    claim: ClaimRecord
    status: Status
    reason: str
    valid_to: date | None
    score: ScoreBreakdown
    confidence: float = Field(ge=0.0, le=1.0)
    superseded_by: list[str] = []
    conflicts_with: list[str] = []
    corroborated_by: list[str] = []
    blocked_by: list[str] = []
