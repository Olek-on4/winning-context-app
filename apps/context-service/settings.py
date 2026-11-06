# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""All weights, thresholds and paths. The scoring is explained in
docs/04-temporal-model.md#scoring — change a number here, not in code."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from models.ontology import SourceType, TimeSignal

# docs/03-ontology.md#source-authority — what kind of artefact, not how sure it sounds.
AUTHORITY: dict[SourceType, float] = {
    SourceType.MIGRATION: 1.00,
    SourceType.CONFIG: 1.00,
    SourceType.CODE: 0.90,
    SourceType.API_SPEC: 0.85,
    SourceType.ADR: 0.80,
    SourceType.RELEASE: 0.80,
    SourceType.DESIGN_DOC: 0.65,
    SourceType.ISSUE: 0.55,
    SourceType.MEETING: 0.50,
    SourceType.WIKI: 0.45,
    SourceType.DIAGRAM: 0.40,
    SourceType.HISTORICAL: 0.20,
    SourceType.OTHER: 0.30,
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

    authority: dict[SourceType, float] = AUTHORITY
    time_confidence: dict[TimeSignal, float] = TIME_CONFIDENCE

    freshness_half_life_days: float = 120.0
    freshness_floor: float = 0.5
    supersede_ratio: float = 0.5
    tie_margin: float = 0.15
    min_confidence: float = 0.40
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
