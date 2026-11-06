"""The one envelope between extraction and the graph.

Frozen contract: every pipeline emits ClaimRecord and nothing else, so a new source
type is a new function and zero edits elsewhere. See docs/05, docs/03.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Polarity(StrEnum):
    ASSERTS = "ASSERTS"
    NEGATES = "NEGATES"


class Modality(StrEnum):
    FACT = "FACT"
    DECISION = "DECISION"
    PROPOSAL = "PROPOSAL"
    PLAN = "PLAN"
    HYPOTHESIS = "HYPOTHESIS"
    PROHIBITION = "PROHIBITION"


class SourceType(StrEnum):
    CODE = "code"
    CONFIG = "config"
    API_SPEC = "api_spec"
    SCHEMA = "schema"
    NARRATIVE = "narrative"
    DIAGRAM = "diagram"


class EntityRef(BaseModel):
    kind: str
    key: str


class Span(BaseModel):
    """A pointer, never stored prose: the text is resolved from (path, lines, hash)."""

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content_hash: str

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.end_line < self.start_line:
            raise ValueError("end_line before start_line")
        return self


class ClaimRecord(BaseModel):
    """One assertion by one source. Pipelines may contradict each other on purpose."""

    subject: EntityRef
    predicate: str
    object: EntityRef | str
    polarity: Polarity = Polarity.ASSERTS
    modality: Modality = Modality.FACT
    valid_from: date | None = None
    valid_from_precision: Literal["day", "month"] = "day"
    valid_to: date | None = None
    valid_to_precision: Literal["day", "month"] | None = None
    observed_at: date | None = None
    evidence: list[Span] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    extractor: str
    extractor_version: str = "1"
    source_type: SourceType = SourceType.NARRATIVE
    authority: float = Field(ge=0.0, le=1.0, default=0.45)

    @property
    def triple(self) -> tuple[str, str, str]:
        """Identity used for grouping; polarity is the claim, not part of the key."""
        obj = self.object.key if isinstance(self.object, EntityRef) else self.object
        return (self.subject.key, self.predicate, obj)

    @property
    def claim_id(self) -> str:
        """Content-derived, so re-running the ETL MERGEs instead of duplicating."""
        import hashlib

        span = self.evidence[0]
        raw = "|".join(
            [
                *self.triple,
                self.polarity.value,
                f"{span.path}:{span.start_line}-{span.end_line}",
                self.extractor_version,
            ]
        )
        return "c_" + hashlib.sha256(raw.encode()).hexdigest()[:16]
