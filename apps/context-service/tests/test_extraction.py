"""Deterministic extraction: the two facts a parser can prove without a model."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ingest.deterministic import extract
from models.claim import Polarity

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
