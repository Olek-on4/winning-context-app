# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from datetime import date
from pathlib import Path

import pytest

from ingest.pipeline import ingest
from models.claim import ClaimRecord
from service import load_claims
from settings import Settings

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 6)


@pytest.fixture(scope="session")
def cfg(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    claims = tmp_path_factory.mktemp("index") / "claims.jsonl"
    return Settings(repo_root=REPO, claims_path=str(claims))


@pytest.fixture(scope="session")
def records(cfg: Settings) -> list[ClaimRecord]:
    report = ingest(cfg)
    assert report.dropped == [], report.dropped
    return load_claims(cfg)
