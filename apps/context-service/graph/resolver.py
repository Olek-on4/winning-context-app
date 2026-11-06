"""What is currently true. Pure functions over claims — no Neo4j, no model, no I/O.

Extraction is allowed to be dumb and to disagree with itself; this module is the only
place that decides a winner. Deterministic, so every outcome is unit-testable.
Implements the resolver in docs/04, minus community detection (cut, ADR-0006).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from models.claim import ClaimRecord, Modality


class Status(StrEnum):
    VALID = "VALID"
    DEPRECATED = "DEPRECATED"
    PLANNED = "PLANNED"
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


TIE_MARGIN = 0.15
# Contradiction-relative freshness (ported from ADR-0007): age only counts against a
# claim when something newer contradicts it. An old fact nobody disputes stays at 1.0.
FRESHNESS_HALF_LIFE_DAYS = 180
FRESHNESS_FLOOR = 0.25
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


def freshness(claim: ClaimRecord, newest_rival: date | None) -> float:
    """Halve per half-life of *contradicted* age, floored. No rival → 1.0."""
    if newest_rival is None or claim.valid_from is None or newest_rival <= claim.valid_from:
        return 1.0
    decay = 0.5 ** ((newest_rival - claim.valid_from).days / FRESHNESS_HALF_LIFE_DAYS)
    return max(FRESHNESS_FLOOR, decay)


def score(claim: ClaimRecord, newest_rival: date | None = None) -> float:
    """Authority × extractor confidence × contradiction-relative freshness."""
    return round(claim.authority * claim.confidence * freshness(claim, newest_rival), 4)


def resolve(claims: list[ClaimRecord], as_of: date | None = None) -> dict[str, Resolved]:
    """Group by triple, then rank. Contradiction never deletes: losers stay, labelled.

    `as_of` defaults to the newest observation in the batch — the corpus snapshot — so a
    fact whose validity window closed before the snapshot is DEPRECATED without anyone
    having to assert a negation.
    """
    now = as_of or max((c.observed_at for c in claims if c.observed_at), default=None)
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

        def rivaled(claim: ClaimRecord, factual: list[ClaimRecord] = factual) -> float:
            opposite_dates = [
                c.valid_from or c.observed_at
                for c in factual
                if c.polarity is not claim.polarity
            ]
            newest = max((d for d in opposite_dates if d), default=None)
            return score(claim, newest)

        for claim in factual:
            out[claim.claim_id].score = rivaled(claim)
        winner = max(factual, key=rivaled)
        same = [c for c in factual if c.polarity is winner.polarity]
        opposite = [c for c in factual if c.polarity is not winner.polarity]
        best_opposite = max(opposite, key=rivaled) if opposite else None

        # No coin flips: near-equal opposing evidence is reported as disagreement.
        if best_opposite and rivaled(winner) - rivaled(best_opposite) <= TIE_MARGIN:
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

    # A closed validity window is the corpus saying "this stopped being true", with or
    # without a rival claim (path rules such as api-specs/history/ produce these).
    for res in out.values():
        if now and res.valid_to and res.valid_to < now and res.status is Status.VALID:
            res.status = Status.DEPRECATED

    return out
