"""What is currently true. Pure functions over claims — no Neo4j, no model, no I/O.

Extraction is allowed to be dumb and to disagree with itself; this module is the only
place that decides a winner. Deterministic, so every outcome is unit-testable.
Implements the resolver in docs/04, minus community detection (cut, ADR-0006).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from models.claim import ClaimRecord, Modality, Polarity


class Status(StrEnum):
    VALID = "VALID"
    DEPRECATED = "DEPRECATED"
    PLANNED = "PLANNED"
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


TIE_MARGIN = 0.15
# Intent is never compared against facts: it is reported as intent.
INTENT_MODALITIES = {Modality.PROPOSAL, Modality.PLAN}


@dataclass
class Resolved:
    claim: ClaimRecord
    status: Status
    score: float
    valid_to: date | None = None
    corroborated_by: int = 0
    confidence: float = 0.0
    contradicts: list[str] = field(default_factory=list)


def score(claim: ClaimRecord) -> float:
    """Authority × the extractor's own confidence. Recency is handled by supersession."""
    return claim.authority * claim.confidence


def resolve(claims: list[ClaimRecord]) -> dict[str, Resolved]:
    """Group by triple, then rank. Contradiction never deletes: losers stay, labelled."""
    groups: dict[tuple[str, str, str], list[ClaimRecord]] = {}
    for claim in claims:
        groups.setdefault(claim.triple, []).append(claim)

    out: dict[str, Resolved] = {
        c.claim_id: Resolved(claim=c, status=Status.UNKNOWN, score=score(c), valid_to=c.valid_to) for c in claims
    }
    prohibited = {c.triple for c in claims if c.modality is Modality.PROHIBITION}

    for triple, group in groups.items():
        factual = [c for c in group if c.modality not in INTENT_MODALITIES and c.modality is not Modality.PROHIBITION]
        intents = [c for c in group if c.modality in INTENT_MODALITIES]

        if triple in prohibited or not factual:
            for claim in intents:
                out[claim.claim_id].status = Status.PROPOSED if claim.modality is Modality.PROPOSAL else Status.PLANNED
            for claim in factual:
                out[claim.claim_id].status = Status.PROPOSED
            continue

        if len(factual) == 1 and factual[0].modality is Modality.HYPOTHESIS:
            # A single unverified claim is a lead, never a fact (T7).
            out[factual[0].claim_id].status = Status.DISPUTED
            continue

        winner = max(factual, key=score)
        same = [c for c in factual if c.polarity is winner.polarity]
        opposite = [c for c in factual if c.polarity is not winner.polarity]
        best_opposite = max(opposite, key=score) if opposite else None

        # No coin flips: near-equal opposing evidence is reported as disagreement.
        if best_opposite and score(winner) - score(best_opposite) <= TIE_MARGIN:
            for claim, other in ((winner, best_opposite), (best_opposite, winner)):
                res = out[claim.claim_id]
                res.status = Status.DISPUTED
                res.contradicts = [other.claim_id]
            continue

        for claim in same:
            res = out[claim.claim_id]
            res.status = Status.VALID
            if len(same) > 1:
                # Independent agreement: 1 − ∏(1 − c_i).
                product = 1.0
                for c in same:
                    product *= 1.0 - c.confidence
                res.corroborated_by = len(same) - 1
                res.confidence = round(1.0 - product, 4)

        if best_opposite:
            # The winner's own date closes the loser's interval; the loser is never removed.
            superseded_at = winner.valid_from or winner.observed_at
            for claim in opposite:
                res = out[claim.claim_id]
                res.status = Status.DEPRECATED
                res.valid_to = superseded_at or claim.valid_to

        for claim in intents:
            out[claim.claim_id].status = Status.PROPOSED if claim.modality is Modality.PROPOSAL else Status.PLANNED

    return out
