"""Trap T1 from the corpus: the wiki says Redis, the ADR removed it in June.

A pass here means the resolver, not a model, decides what is currently true.
"""

from __future__ import annotations

from datetime import date

from graph.resolver import Status, resolve
from models.claim import ClaimRecord, EntityRef, Modality, Polarity, SourceType, Span

SERVICE = EntityRef(kind="Service", key="inventory-service")


def claim(**kw) -> ClaimRecord:
    base = dict(
        subject=SERVICE,
        predicate="READS_FROM",
        evidence=[Span(path="x.md", start_line=1, end_line=1, content_hash="h")],
        extractor="test",
        observed_at=date(2026, 2, 17),
    )
    return ClaimRecord(**{**base, **kw})


def test_removed_cache_is_deprecated_by_the_decision_that_removed_it():
    wiki = claim(
        object="Redis", observed_at=date(2026, 2, 17), confidence=0.9,
        authority=0.45, source_type=SourceType.NARRATIVE, valid_from=date(2026, 1, 1),
    )
    adr = claim(
        object="Redis", polarity=Polarity.NEGATES, modality=Modality.DECISION,
        observed_at=date(2026, 6, 4), confidence=0.95, authority=0.80,
        source_type=SourceType.NARRATIVE, valid_from=date(2026, 6, 4),
    )

    result = resolve([wiki, adr])

    assert result[adr.claim_id].status is Status.VALID
    assert result[wiki.claim_id].status is Status.DEPRECATED
    assert result[wiki.claim_id].valid_to == date(2026, 6, 4)


def test_independent_sources_corroborate_instead_of_competing():
    release = claim(
        object="SQLite", observed_at=date(2026, 6, 1), confidence=0.8,
        authority=0.80, source_type=SourceType.NARRATIVE, valid_from=date(2026, 6, 1),
    )
    code = claim(
        object="SQLite", observed_at=date(2026, 6, 5), confidence=0.9,
        authority=0.90, source_type=SourceType.CODE, valid_from=date(2026, 6, 5),
    )

    result = resolve([release, code])

    assert result[release.claim_id].status is Status.VALID
    assert result[code.claim_id].status is Status.VALID
    assert result[code.claim_id].corroborated_by == 1
    assert result[code.claim_id].confidence == 0.98


def test_near_equal_opposing_claims_stay_disputed():
    # Equal authority and confidence: the service must not pick a winner.
    a = claim(object="Redis", observed_at=date(2026, 5, 1), confidence=0.8, authority=0.8)
    b = claim(object="Redis", polarity=Polarity.NEGATES, observed_at=date(2026, 5, 2), confidence=0.8, authority=0.8)

    result = resolve([a, b])

    assert result[a.claim_id].status is Status.DISPUTED
    assert result[b.claim_id].status is Status.DISPUTED
    assert result[a.claim_id].contradicts == [b.claim_id]


def test_proposal_is_never_promoted_to_valid():
    proposal = claim(
        object="SSO", predicate="AUTHENTICATES_VIA", modality=Modality.PROPOSAL,
        confidence=0.9, authority=0.8, observed_at=date(2026, 9, 1),
    )

    result = resolve([proposal])

    assert result[proposal.claim_id].status is Status.PROPOSED


def test_single_hypothesis_stays_disputed():
    lead = claim(object="CWE-639", predicate="VIOLATES", modality=Modality.HYPOTHESIS, confidence=0.6, authority=0.55)

    result = resolve([lead])

    assert result[lead.claim_id].status is Status.DISPUTED


def test_age_only_counts_when_something_newer_contradicts():
    """A 2024 fact nobody disputes keeps status and score; the decay is relative."""
    old_undisputed = claim(
        object="SQLite", predicate="READS_FROM", observed_at=date(2024, 1, 1),
        valid_from=date(2024, 1, 1), confidence=0.9, authority=0.8,
    )
    old_contradicted = claim(
        object="Redis", observed_at=date(2024, 1, 1), valid_from=date(2024, 1, 1),
        confidence=0.9, authority=0.8,
    )
    later_removal = claim(
        object="Redis", polarity=Polarity.NEGATES, modality=Modality.DECISION,
        observed_at=date(2026, 6, 4), valid_from=date(2026, 6, 4),
        confidence=0.95, authority=0.8,
    )

    result = resolve([old_undisputed, old_contradicted, later_removal])

    assert result[old_undisputed.claim_id].score == 0.72          # 0.8 × 0.9, no decay
    assert result[old_contradicted.claim_id].score < 0.72          # decayed by ~880 days
    assert result[old_contradicted.claim_id].score >= 0.72 * 0.25  # floored


def test_a_diagram_alone_is_a_lead_not_a_fact():
    """Issue 9: diagram claims are capped at authority 0.40 — alone they stay DISPUTED."""
    from models.claim import SourceType

    diagram_only = claim(
        object="Redis", observed_at=date(2026, 1, 15), valid_from=date(2026, 1, 1),
        confidence=0.9, authority=0.40, source_type=SourceType.DIAGRAM,
    )

    result = resolve([diagram_only])

    assert result[diagram_only.claim_id].status is Status.DISPUTED


def test_a_proposal_realised_by_a_later_fact_stops_being_a_proposal():
    """Issue 9: `PROPOSED` is a state, not a verdict — a realised proposal is VALID."""
    proposal = claim(
        object="SSO", predicate="AUTHENTICATES_VIA", modality=Modality.PROPOSAL,
        observed_at=date(2026, 3, 1), valid_from=date(2026, 3, 1), confidence=0.9, authority=0.8,
    )
    shipped = claim(
        object="SSO", predicate="AUTHENTICATES_VIA", modality=Modality.FACT,
        observed_at=date(2026, 9, 1), valid_from=date(2026, 9, 1), confidence=0.9, authority=0.8,
    )

    result = resolve([proposal, shipped])

    assert result[shipped.claim_id].status is Status.VALID
    assert result[proposal.claim_id].status is Status.VALID
