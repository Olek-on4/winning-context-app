"""The claim row that reaches Neo4j: every property the answer path reads must be written.

A field the query selects but the loader never sets is silently null at `detail=high` - the
kind of provenance gap that looks like a bug in the extractor instead of the loader.
"""

from __future__ import annotations

from datetime import date

from graph.loader import UPSERT_CLAIM
from models.claim import ClaimRecord, EntityRef, SourceType, Span

PROPERTIES = (
    "predicate",
    "polarity",
    "modality",
    "status",
    "confidence",
    "valid_from",
    "valid_to",
    "observed_at",
    "extractor",
    "extractor_version",
    "source_type",
    "authority",
)


def test_the_upsert_writes_every_property_the_retrieval_query_selects():
    for name in PROPERTIES:
        assert f"cl.{name} = c.{name}" in UPSERT_CLAIM, name


def test_a_claim_carries_the_authority_the_answer_reports():
    claim = ClaimRecord(
        subject=EntityRef(key="inventory-service", kind="Service"),
        predicate="READS_FROM",
        object="sqlite",
        observed_at=date(2026, 6, 4),
        confidence=0.9,
        extractor="adr",
        authority=0.82,
        source_type=SourceType.ADR,
        evidence=[Span(path="docs/adr/003.md", start_line=1, end_line=1, content_hash="0" * 64)],
    )

    assert claim.authority == 0.82
