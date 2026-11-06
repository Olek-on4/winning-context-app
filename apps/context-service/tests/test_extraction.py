"""Deterministic extraction: the two facts a parser can prove without a model."""

from __future__ import annotations

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
