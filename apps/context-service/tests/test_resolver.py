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
