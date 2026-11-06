# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""score = authority × time_confidence × extractor_confidence × freshness.
Explained, with worked numbers, in docs/04-temporal-model.md#scoring."""

from collections.abc import Iterable
from datetime import date

from models.claim import ClaimRecord, ScoreBreakdown
from settings import Settings


def freshness(valid_from: date, later_contradictions: Iterable[date], cfg: Settings) -> float:
    """Halves every `half_life` days by which the newest contradicting claim is newer.
    No contradiction → 1.0: an old fact nobody disputes is not less true for being old."""
    newest = max((d for d in later_contradictions if d > valid_from), default=None)
    if newest is None:
        return 1.0
    decay = 0.5 ** ((newest - valid_from).days / cfg.freshness_half_life_days)
    return max(cfg.freshness_floor, decay)


def score(claim: ClaimRecord, fresh: float, cfg: Settings) -> ScoreBreakdown:
    authority = cfg.authority[claim.source_type]
    time_conf = cfg.time_confidence[claim.time_signal] if claim.time_signal else 0.0
    value = authority * time_conf * claim.confidence * fresh
    return ScoreBreakdown(
        authority=authority,
        time_confidence=time_conf,
        extractor_confidence=claim.confidence,
        freshness=round(fresh, 4),
        score=round(value, 4),
    )


def corroborate(scores_by_source_type: Iterable[float]) -> float:
    """Independent sources agreeing: 1 − ∏(1 − sᵢ). One score per source type, so
    three wiki pages copying each other count once."""
    miss = 1.0
    for s in scores_by_source_type:
        miss *= 1.0 - s
    return round(1.0 - miss, 4)
