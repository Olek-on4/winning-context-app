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
    """Where a fact was read from. Fine enough to filter by, coarse enough to stay stable."""

    CODE = "code"
    CONFIG = "config"
    API_SPEC = "api_spec"
    SCHEMA = "schema"
    DIAGRAM = "diagram"
    ADR = "adr"
    RELEASE = "release"
    ISSUE = "issue"
    MEETING = "meeting"
    WIKI = "wiki"
    DESIGN_DOC = "design_doc"
    HISTORICAL = "historical"  # api-specs/history/, archive/: superseded by path
    NARRATIVE = "narrative"    # prose whose kind the path does not reveal


class DocStatus(StrEnum):
    """A document's own claim about its lifecycle, when it makes one."""

    ACCEPTED = "accepted"
    PROPOSED = "proposed"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"
    OPEN = "open"
    CLOSED = "closed"


class EntityRef(BaseModel):
    kind: str
    key: str


class Region(BaseModel):
    """A rectangle in an image, in pixels from the top-left corner.

    An image has no lines to cite, so a diagram claim points at where it was read. Every
    leg of the span gate that works on text is replaced by one that works on geometry:
    the rectangle must be inside the file's real dimensions and its digest must match.
    """

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)

    def __str__(self) -> str:
        return f"{self.x},{self.y},{self.w},{self.h}"


class Span(BaseModel):
    """A pointer, never stored prose: the text is resolved from (path, lines, hash).

    A region is present only for image sources; `start_line == end_line == 1` is then the
    sentinel, because the record still has to say where in the file it looked.
    """

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content_hash: str
    region: Region | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.end_line < self.start_line:
            raise ValueError("end_line before start_line")
        if self.region is not None and (self.start_line, self.end_line) != (1, 1):
            raise ValueError("a region span cites the whole file: start_line and end_line must be 1")
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
    doc_status: DocStatus | None = None
    modality_capped_from: Modality | None = None
    authority: float = Field(ge=0.0, le=1.0, default=0.45)
    # Verification input for the span gate; the loader stores the pointer, never this text.
    excerpt: str | None = None

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
        where = f"{span.path}:{span.start_line}-{span.end_line}"
        if span.region is not None:
            # Two facts read from two places in one image are two claims, not one.
            where = f"{where}@{span.region}"
        raw = "|".join([*self.triple, self.polarity.value, where, self.extractor_version])
        return "c_" + hashlib.sha256(raw.encode()).hexdigest()[:16]
