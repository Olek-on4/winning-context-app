# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""All weights, thresholds and per-data-type rules. The scoring is explained in
docs/04-temporal-model.md#scoring-and-the-quality-filter — change a row here, not code.
A new kind of source is one row in SOURCES; a new document status is one row in
DOC_STATUSES. Nothing else in the code names a source type or a status."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from models.ontology import DocStatus, Modality, SourceType, TimeSignal


class SourcePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    authority: float
    """What kind of artefact said it — machine-executed beats prose (docs/03)."""
    deprecated_by_path: bool = False
    """The path itself says superseded or abandoned (`api-specs/history/`, `archive/`)."""
    needs_corroboration: bool = False
    """Never VALID alone: a second, different source type must agree."""


class DocStatusPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    settledness: float
    """How final the document says it is. Multiplies the score."""
    decision_becomes: Modality | None = None
    """An unsettled document cannot decide: its DECISION claims are capped to this."""


SOURCES: dict[SourceType, SourcePolicy] = {
    SourceType.MIGRATION: SourcePolicy(authority=1.00),
    SourceType.CONFIG: SourcePolicy(authority=1.00),
    SourceType.CODE: SourcePolicy(authority=0.90),
    SourceType.API_SPEC: SourcePolicy(authority=0.85),
    SourceType.ADR: SourcePolicy(authority=0.80),
    SourceType.RELEASE: SourcePolicy(authority=0.80),
    SourceType.DESIGN_DOC: SourcePolicy(authority=0.65),
    SourceType.ISSUE: SourcePolicy(authority=0.55),
    SourceType.MEETING: SourcePolicy(authority=0.50),
    SourceType.WIKI: SourcePolicy(authority=0.45),
    SourceType.DIAGRAM: SourcePolicy(authority=0.40, needs_corroboration=True),
    SourceType.HISTORICAL: SourcePolicy(authority=0.20, deprecated_by_path=True),
    SourceType.OTHER: SourcePolicy(authority=0.30),
}

DOC_STATUSES: dict[DocStatus, DocStatusPolicy] = {
    DocStatus.ACCEPTED: DocStatusPolicy(settledness=1.00),
    DocStatus.CLOSED: DocStatusPolicy(settledness=1.00),
    DocStatus.ACCEPTED_WITH_REVIEW: DocStatusPolicy(settledness=0.90),
    DocStatus.DESIGN_REVIEW: DocStatusPolicy(settledness=0.80, decision_becomes=Modality.PROPOSAL),
    DocStatus.OPEN: DocStatusPolicy(settledness=0.75, decision_becomes=Modality.PROPOSAL),
    DocStatus.INVESTIGATING: DocStatusPolicy(settledness=0.75, decision_becomes=Modality.PROPOSAL),
    DocStatus.DEFERRED: DocStatusPolicy(settledness=0.70, decision_becomes=Modality.PLAN),
    DocStatus.UNTRIAGED: DocStatusPolicy(settledness=0.60, decision_becomes=Modality.PROPOSAL),
    DocStatus.PROPOSED: DocStatusPolicy(settledness=0.60, decision_becomes=Modality.PROPOSAL),
}

# docs/04-temporal-model.md#where-time-comes-from — how trustworthy the date is.
TIME_CONFIDENCE: dict[TimeSignal, float] = {
    TimeSignal.EXPLICIT_FIELD: 1.00,
    TimeSignal.FILENAME: 0.95,
    TimeSignal.BYLINE: 0.90,
    TimeSignal.REFERENCED_RECORD: 0.85,
    TimeSignal.DIAGRAM_TITLE: 0.70,
    TimeSignal.GIT: 0.60,
}


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo_root: Path
    corpus_dir: str = "vendor/att-hackathon-task"
    fixtures_path: str = "data/fixtures/claims-sample.jsonl"
    diagram_transcripts_dir: str = "data/fixtures/diagrams"
    claims_path: str = "data/local/claims.jsonl"

    sources: dict[SourceType, SourcePolicy] = SOURCES
    doc_statuses: dict[DocStatus, DocStatusPolicy] = DOC_STATUSES
    time_confidence: dict[TimeSignal, float] = TIME_CONFIDENCE

    freshness_half_life_days: float = 120.0
    freshness_floor: float = 0.5
    supersede_ratio: float = 0.5
    tie_margin: float = 0.15
    min_confidence: float = 0.40
    min_source_types: int = 1
    token_budget: int = 2000
    max_statements: int = 8

    @property
    def corpus_root(self) -> Path:
        return self.repo_root / self.corpus_dir

    def resolve_path(self, relative: str) -> Path:
        return self.repo_root / relative


_ENV_SCALARS = (
    "corpus_dir",
    "claims_path",
    "freshness_half_life_days",
    "freshness_floor",
    "supersede_ratio",
    "tie_margin",
    "min_confidence",
    "min_source_types",
    "token_budget",
    "max_statements",
)


def load_settings() -> Settings:
    """NCS_REPO_ROOT and NCS_<FIELD> override the defaults."""
    overrides: dict[str, str] = {
        name: os.environ[f"NCS_{name.upper()}"]
        for name in _ENV_SCALARS
        if f"NCS_{name.upper()}" in os.environ
    }
    root = Path(os.environ.get("NCS_REPO_ROOT", Path.cwd()))
    return Settings.model_validate({"repo_root": root, **overrides})
