# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from ingest.dates import date_from_content
from ingest.gates import Source, locate
from ingest.headers import declared_status
from ingest.pipeline import ingest
from ingest.router import source_type
from models.claim import ClaimRecord, EvidenceHint
from models.ontology import DocStatus, Modality, Precision, SourceType, TimeSignal
from settings import Settings

CORPUS = Path(__file__).resolve().parents[2] / "vendor/att-hackathon-task"


def _lines(path: str) -> list[str]:
    return (CORPUS / path).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("api-specs/history/accounts-v1.md", SourceType.HISTORICAL),
        ("archive/conference-registration/README.md", SourceType.HISTORICAL),
        ("apps/user-service/migrations/002-account-tiers.sql", SourceType.MIGRATION),
        ("config/ports.json", SourceType.CONFIG),
        ("apps/inventory-service/app.py", SourceType.CODE),
        ("api-specs/user-service.md", SourceType.API_SPEC),
        ("docs/adr/003-stock-cache.md", SourceType.ADR),
        ("releases/2026-06-v1.3.md", SourceType.RELEASE),
        ("issues/SEC-22.md", SourceType.ISSUE),
        ("incidents/2026-06-02-stock-read.md", SourceType.ISSUE),
        ("meeting-notes/2026-06-04-cache-removal.md", SourceType.MEETING),
        ("wiki/inventory-service.md", SourceType.WIKI),
        ("diagrams/architecture-january.png", SourceType.DIAGRAM),
    ],
)
def test_router_reads_type_from_path(path: str, expected: SourceType) -> None:
    assert source_type(path) is expected


@pytest.mark.parametrize(
    ("path", "on", "precision", "signal"),
    [
        ("docs/adr/003-stock-cache.md", date(2026, 6, 4), Precision.DAY, TimeSignal.EXPLICIT_FIELD),
        (
            "meeting-notes/2026-06-04-cache-removal.md",
            date(2026, 6, 4),
            Precision.DAY,
            TimeSignal.FILENAME,
        ),
        ("releases/2026-06-v1.3.md", date(2026, 6, 1), Precision.MONTH, TimeSignal.FILENAME),
        ("wiki/inventory-service.md", date(2026, 2, 17), Precision.DAY, TimeSignal.BYLINE),
        ("wiki/accounts-http.md", date(2026, 2, 3), Precision.DAY, TimeSignal.BYLINE),
        ("issues/SEC-22.md", date(2026, 9, 11), Precision.DAY, TimeSignal.BYLINE),
        ("api-specs/history/accounts-v1.md", date(2026, 1, 20), Precision.DAY, TimeSignal.BYLINE),
    ],
)
def test_dates_come_from_the_file(
    path: str, on: date, precision: Precision, signal: TimeSignal
) -> None:
    dated = date_from_content(path, _lines(path))
    assert dated is not None
    assert (dated.on, dated.precision, dated.signal) == (on, precision, signal)


def test_code_has_no_intrinsic_date() -> None:
    assert (
        date_from_content("apps/inventory-service/app.py", _lines("apps/inventory-service/app.py"))
        is None
    )


def test_diagram_date_comes_from_its_title() -> None:
    title = ["Northstar architecture / January 2026 / winter review"]
    dated = date_from_content("diagrams/architecture-january.png", title)
    assert dated is not None
    assert (dated.on, dated.signal) == (date(2026, 1, 1), TimeSignal.DIAGRAM_TITLE)


def _source(path: str) -> Source:
    raw = (CORPUS / path).read_bytes()
    return Source(raw.decode("utf-8").splitlines(), hashlib.sha256(raw).hexdigest())


def test_span_gate_accepts_moves_or_drops() -> None:
    src = _source("wiki/inventory-service.md")
    quote = "Core Platform owns Stock and its Redis read cache."

    exact = locate(EvidenceHint(path="wiki/inventory-service.md", start_line=5, excerpt=quote), src)
    moved = locate(EvidenceHint(path="wiki/inventory-service.md", start_line=9, excerpt=quote), src)
    paraphrase = EvidenceHint(
        path="wiki/inventory-service.md",
        start_line=5,
        excerpt="Core Platform owns the Redis cache.",
    )

    assert exact is not None and exact[0].start_line == 5 and exact[1] is False
    assert moved is not None and moved[0].start_line == 5 and moved[1] is True
    assert exact[0].content_hash == src.content_hash
    assert locate(paraphrase, src) is None


def test_migration_is_dated_by_the_release_that_shipped_it(records: list[ClaimRecord]) -> None:
    rename = next(
        r for r in records
        if r.evidence[0].path.endswith("002-account-tiers.sql") and r.polarity == "NEGATES"
    )  # fmt: skip
    assert rename.observed_at == date(2026, 3, 1)
    assert rename.time_signal is TimeSignal.REFERENCED_RECORD


def test_ingest_drops_a_tampered_claim_and_says_why(cfg: Settings, tmp_path: Path) -> None:
    source = cfg.resolve_path(cfg.fixtures_path).read_text(encoding="utf-8").splitlines()
    tampered = json.loads(source[0])
    tampered["evidence"][0]["excerpt"] = "Core Platform owns Stock and its Memcached read cache."
    fixture = tmp_path / "claims.jsonl"
    fixture.write_text("\n".join([json.dumps(tampered), source[1]]) + "\n", encoding="utf-8")
    local = cfg.model_copy(update={"claims_path": str(tmp_path / "out.jsonl")})

    report = ingest(local, fixture)

    assert report.written == 1
    assert len(report.dropped) == 1
    assert "excerpt not found in wiki/inventory-service.md" in report.dropped[0]


def test_ingest_is_byte_identical_on_rerun(cfg: Settings, tmp_path: Path) -> None:
    out = [tmp_path / "a.jsonl", tmp_path / "b.jsonl"]
    for path in out:
        ingest(cfg.model_copy(update={"claims_path": str(path)}))
    assert out[0].read_bytes() == out[1].read_bytes()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/adr/003-stock-cache.md", DocStatus.ACCEPTED),
        ("docs/adr/004-people-sso.md", DocStatus.PROPOSED),
        ("docs/adr/005-support-access.md", DocStatus.ACCEPTED_WITH_REVIEW),
        ("issues/INV-190.md", DocStatus.CLOSED),
        ("issues/SEC-22.md", DocStatus.OPEN),
        ("issues/EDGE-53.md", DocStatus.DEFERRED),
        ("issues/PAY-118.md", DocStatus.INVESTIGATING),
        ("issues/LAB-12.md", DocStatus.UNTRIAGED),
        ("issues/PEOPLE-71.md", DocStatus.DESIGN_REVIEW),
        ("wiki/inventory-service.md", None),
        ("meeting-notes/2026-06-04-cache-removal.md", None),
    ],
)
def test_one_status_reader_for_every_document_type(path: str, expected: DocStatus | None) -> None:
    assert declared_status(_lines(path)) == expected


def test_deferred_ticket_cannot_decide(records: list[ClaimRecord]) -> None:
    edge = next(r for r in records if r.evidence[0].path == "issues/EDGE-53.md")
    assert edge.declared_status is DocStatus.DEFERRED
    assert (edge.modality_capped_from, edge.modality) == (Modality.DECISION, Modality.PLAN)
