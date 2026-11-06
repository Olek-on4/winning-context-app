# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Query filter and answer envelope (docs/06-retrieval.md#answer-assembly)."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from models.claim import EntityRef, ScoreBreakdown
from models.ontology import Polarity, Predicate, SourceType, Status, Verdict

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class TimeFilter(BaseModel):
    """The `time` block of the CQP. Every status is returned by default — labelled,
    in `not_valid` — because hiding a stale claim leaves the agent unable to say why
    the wiki disagrees. Pass `status_in=[VALID]` for current-truth only."""

    model_config = _FROZEN
    as_of: date | None = None
    status_in: list[Status] = list(Status)


class EvidenceFilter(BaseModel):
    """The `evidence` block of the CQP. None means the configured default."""

    model_config = _FROZEN
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Citation(BaseModel):
    """`excerpt` is already wrapped in <untrusted_source> — corpus text is data."""

    model_config = _FROZEN
    path: str
    lines: tuple[int, int]
    excerpt: str
    via: str | None = None


class Statement(BaseModel):
    model_config = _FROZEN
    text: str
    subject: EntityRef
    predicate: Predicate
    object: EntityRef
    polarity: Polarity
    verdict: Verdict
    status: Status
    reason: str
    valid_from: date | None
    valid_to: date | None
    confidence: float
    score: ScoreBreakdown
    source_types: list[SourceType]
    citations: list[Citation]
    superseded_by: list[Citation] = []


class Conflict(BaseModel):
    model_config = _FROZEN
    statements: list[str]
    reason: str


class Answer(BaseModel):
    model_config = _FROZEN
    question: str
    as_of: date
    answer: str
    claims: list[Statement]
    not_valid: list[Statement]
    conflicts: list[Conflict]
    gaps: list[str]
    degraded: bool
    degraded_reason: str | None
    truncated: bool
