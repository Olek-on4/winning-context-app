"""Deterministic extraction: the two facts a parser can prove without a model."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ingest.deterministic import extract
from models.claim import ClaimRecord, EntityRef, Polarity, Span
from sources import Root, discover, hash_file

CORPUS = Path(__file__).resolve().parents[3] / "vendor" / "att-hackathon-task"


def test_rename_migration_yields_a_negation_and_an_assertion():
    claims = [c for c in extract(CORPUS) if c.predicate == "HAS_COLUMN" and c.subject.key == "users"]

    negated = [c for c in claims if c.polarity is Polarity.NEGATES and c.object == "status"]
    asserted = [c for c in claims if c.polarity is Polarity.ASSERTS and c.object == "account_status"]

    assert negated and asserted
    assert all(c.observed_at is not None for c in claims)
    assert negated[0].evidence[0].path.endswith("002-account-tiers.sql")


def test_ports_map_is_extracted_with_a_span_per_service():
    claims = {c.subject.key: c for c in extract(CORPUS) if c.predicate == "LISTENS_ON"}

    assert claims["inventory-service"].object == "5005"
    assert claims["inventory-service"].authority == 1.0
    assert claims["inventory-service"].evidence[0].start_line >= 1


def test_locate_relocates_a_wrong_hint_and_refuses_a_missing_excerpt():
    """Issue 3: the model's line is a hint; the file decides."""
    from ingest.gates import locate

    lines = ["# title", "Status: Accepted", "body text", "more body"]

    assert locate(lines, "body text", hint=3) == (3, 3, False)
    assert locate(lines, "Status: Accepted", hint=4) == (2, 2, True)
    assert locate(lines, "not in this file", hint=1) is None


def test_an_undated_migration_takes_its_date_from_the_release_that_ships_it():
    from ingest.gates import dated_by_reference
    from sources import discover

    root = discover([CORPUS])[0]
    assert dated_by_reference(root, "002-account-tiers.sql") == date(2026, 3, 1)
    assert dated_by_reference(root, "001-users.sql") is None


def _claim_at(tmp_path: Path, excerpt: str | None, line: int) -> tuple[Root, ClaimRecord]:
    """One markdown claim; the excerpt is what the span gate has to find."""
    target = tmp_path / "doc.md"
    target.write_text("# title\nStatus: Accepted\nbody text\nmore body\n", encoding="utf-8")
    [root] = discover([tmp_path])
    claim = ClaimRecord(
        subject=EntityRef(kind="Document", key="doc"),
        predicate="HAS_STATUS",
        object="Accepted",
        evidence=[Span(path=root.pointer(Path("doc.md")), start_line=line, end_line=line,
                       content_hash=hash_file(target))],
        confidence=1.0,
        extractor="test",
        observed_at=date(2026, 3, 1),
        excerpt=excerpt,
    )
    return root, claim


def test_span_gate_keeps_a_verbatim_excerpt(tmp_path):
    """Issue 73: the gate is on the load path, not a library nobody calls."""
    from ingest.gates import verify
    from sources import SpanStore

    root, claim = _claim_at(tmp_path, "Status: Accepted", 2)
    kept, counts = verify([claim], SpanStore([root]))

    assert [c.claim_id for c in kept] == [claim.claim_id]
    assert (counts.kept, counts.dropped, counts.relocated, counts.ungeated) == (1, 0, 0, 0)
    assert counts.pass_rate == 1.0
    assert kept[0].evidence[0].start_line == 2


def test_span_gate_drops_an_excerpt_that_is_not_in_the_file(tmp_path, capsys):
    from ingest.gates import verify
    from sources import SpanStore

    root, claim = _claim_at(tmp_path, "Status: Rejected", 2)
    kept, counts = verify([claim], SpanStore([root]))

    assert kept == []
    assert (counts.kept, counts.dropped, counts.pass_rate) == (0, 1, 0.0)
    assert claim.claim_id in capsys.readouterr().err  # the reason names the claim and the range


def test_span_gate_loads_a_pointer_only_claim_ungeated(tmp_path):
    from ingest.gates import verify
    from sources import SpanStore

    root, claim = _claim_at(tmp_path, None, 2)
    kept, counts = verify([claim], SpanStore([root]))

    assert len(kept) == 1
    assert (counts.kept, counts.ungeated, counts.pass_rate) == (0, 1, None)


def test_span_gate_relocates_a_line_that_moved_by_two(tmp_path):
    from ingest.gates import verify
    from sources import SpanStore

    root, claim = _claim_at(tmp_path, "Status: Accepted", 4)  # the text is on line 2
    kept, counts = verify([claim], SpanStore([root]))

    assert (counts.kept, counts.relocated) == (1, 1)
    assert kept[0].evidence[0].start_line == 2


def test_an_explicit_date_line_dates_a_non_git_root(tmp_path):
    """Issue 84: a declared date outranks mtime, so a non-git corpus stays ordered."""
    from ingest import registry
    from sources import discover

    base = tmp_path / "notes"
    base.mkdir()
    if any((parent / ".git").exists() for parent in (base, *base.parents)):
        pytest.skip("temporary directory sits inside a git work tree")
    (base / "decision.md").write_text("# Choice\n\nDate: 2026-03-01\nStatus: Accepted\n", encoding="utf-8")

    [root] = discover([base])
    claims = registry.extract(root)

    assert {c.observed_at for c in claims} == {date(2026, 3, 1)}
    assert all(c.excerpt for c in claims)  # extraction hands the gate a quote to verify


def test_confidence_says_how_certain_the_extractor_is(tmp_path):
    """All six pipelines used to report 1.0, which told a reader nothing."""
    from ingest.registry import _confidence
    from settings import DEFAULT_EXTRACTOR_CONFIDENCE, EXTRACTOR_CONFIDENCE

    assert _confidence("sql.alter") > _confidence("prose.mention")
    assert _confidence("unknown.pipeline") == DEFAULT_EXTRACTOR_CONFIDENCE
    assert all(0.0 < value <= 1.0 for value in EXTRACTOR_CONFIDENCE.values())
