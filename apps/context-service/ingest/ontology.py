"""Gate 3: a predicate must exist in the taxonomy and stay in its declared range.

Docs/03 calls this the ontology gate. It runs where the span gate runs — before a
claim reaches the graph — and a violation is logged with the record and dropped,
never repaired: a claim whose shape is impossible is a pipeline bug, not a near miss.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.claim import ClaimRecord
from settings import PREDICATES


@dataclass(frozen=True)
class Rejection:
    claim: ClaimRecord
    reason: str

    def line(self) -> str:
        return f"{self.claim.claim_id} {self.reason}"


def check(claim: ClaimRecord) -> str | None:
    """None when the claim is in range, else the reason it is not."""
    shaped = PREDICATES.get(claim.predicate)
    if shaped is None:
        return f"unknown predicate {claim.predicate!r}"
    subjects, objects = shaped
    if claim.subject.kind not in subjects:
        return f"{claim.predicate} does not apply to subject kind {claim.subject.kind!r}"
    if objects is None or isinstance(claim.object, str):
        return None
    if claim.object.kind not in objects:
        return f"{claim.predicate} does not allow object kind {claim.object.kind!r}"
    return None


def validate(claims: list[ClaimRecord]) -> tuple[list[ClaimRecord], list[Rejection]]:
    """Partition in input order; the caller logs the rejections with their span."""
    kept: list[ClaimRecord] = []
    rejected: list[Rejection] = []
    for claim in claims:
        reason = check(claim)
        if reason is None:
            kept.append(claim)
        else:
            rejected.append(Rejection(claim, reason))
    return kept, rejected
