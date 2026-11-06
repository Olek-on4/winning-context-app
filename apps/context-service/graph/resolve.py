# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Temporal resolver: claims → status. Deterministic, no model, no database.
Algorithm and rationale: docs/04-temporal-model.md#resolution-algorithm."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from graph.scoring import corroborate, freshness, score
from models.claim import ClaimRecord, EntityRef, ResolvedClaim, ScoreBreakdown
from models.ontology import Modality, Polarity, Precision, SourceType, Status
from settings import Settings

_FACTUAL = {Modality.FACT, Modality.DECISION}
_INTENT = {Modality.PROPOSAL, Modality.PLAN}


@dataclass
class _Work:
    claim: ClaimRecord
    score: ScoreBreakdown
    status: Status | None = None
    reason: str = ""
    valid_to: date | None = None
    valid_to_precision: Precision | None = None
    confidence: float = 0.0
    superseded_by: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    corroborated_by: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)

    @property
    def s(self) -> float:
        return self.score.score

    @property
    def since(self) -> date:
        assert self.claim.valid_from is not None
        return self.claim.valid_from

    def set(self, status: Status, reason: str) -> None:
        self.status, self.reason = status, reason

    def close_at(self, end: "_Work") -> None:
        """A month-precision successor closes at the month's last day, so a June
        supersession never appears to take effect on June 1 (docs/04, partial dates)."""
        on, precision = end.since, end.claim.valid_from_precision
        if precision is Precision.MONTH:
            on = (on.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        self.valid_to, self.valid_to_precision = on, precision


def _cite(w: _Work) -> str:
    span = w.claim.evidence[0]
    return f"{span.path}:{span.start_line}"


def _key(ref: EntityRef) -> str:
    return f"{ref.kind}:{ref.key}"


def _strongest(ws: Sequence[_Work]) -> _Work:
    return max(ws, key=lambda w: (w.s, w.claim.id))


def _supersede(facts: list[_Work], as_of: date, cfg: Settings) -> None:
    """A later fact of opposite polarity closes an earlier one — unless it is so much
    weaker (score < supersede_ratio × earlier) that a wiki could overrule a migration."""
    for w in facts:
        later = [
            d
            for d in facts
            if d.claim.polarity != w.claim.polarity
            and d.since > w.since
            and d.s >= cfg.supersede_ratio * w.s
        ]
        if later:
            best = _strongest(later)
            w.close_at(best)
            w.superseded_by = sorted(d.claim.id for d in later)
            if w.valid_to and w.valid_to > as_of:
                w.set(Status.DISPUTED, f"superseded during {best.since:%Y-%m}; day unknown")
                continue
            w.set(Status.DEPRECATED, f"superseded on {w.valid_to} by {_cite(best)}")


def _rank_open(facts: list[_Work], cfg: Settings) -> None:
    open_ = [w for w in facts if w.status is None]
    sides = {p: [w for w in open_ if w.claim.polarity == p] for p in Polarity}
    yes, no = sides[Polarity.ASSERTS], sides[Polarity.NEGATES]
    if not (yes and no):
        for w in open_:
            w.set(Status.VALID, "no open contradiction")
        return

    top_yes, top_no = _strongest(yes), _strongest(no)
    for w in open_:
        other = no if w.claim.polarity is Polarity.ASSERTS else yes
        w.conflicts_with = sorted(o.claim.id for o in other)
    if abs(top_yes.s - top_no.s) <= cfg.tie_margin:
        for w in open_:
            w.set(Status.DISPUTED, "contemporaneous conflict, scores within tie margin")
        return
    winners, losers, top = (yes, no, top_yes) if top_yes.s > top_no.s else (no, yes, top_no)
    for w in winners:
        w.set(Status.VALID, "outweighs contradicting evidence")
    for w in losers:
        w.set(Status.DISPUTED, f"contradicted by stronger evidence at {_cite(top)}")


def _hypotheses(ws: list[_Work]) -> None:
    for w in ws:
        if w.claim.modality is not Modality.HYPOTHESIS:
            continue
        support = [
            v
            for v in ws
            if v is not w
            and v.claim.polarity == w.claim.polarity
            and v.claim.source_type != w.claim.source_type
            and (v.status is Status.VALID or v.claim.modality is Modality.HYPOTHESIS)
        ]
        if support:
            w.set(Status.VALID, "hypothesis corroborated by an independent source type")
        else:
            w.set(Status.DISPUTED, "reported, not verified: a single-source hypothesis")


def _needs_corroboration(ws: list[_Work], cfg: Settings) -> None:
    """Source types that are never enough alone (diagrams): VALID only if a source type
    without that flag agrees."""
    for p in Polarity:
        valid = [w for w in ws if w.status is Status.VALID and w.claim.polarity == p]
        if valid and all(cfg.sources[w.claim.source_type].needs_corroboration for w in valid):
            kinds = "/".join(sorted({w.claim.source_type.lower() for w in valid}))
            for w in valid:
                w.set(Status.DISPUTED, f"{kinds}-only evidence; needs another source type")


def _intent(ws: list[_Work], prohibitions: dict[str, list[_Work]]) -> None:
    facts = [w for w in ws if w.status is Status.VALID and w.claim.modality in _FACTUAL]
    for w in ws:
        if w.claim.modality not in _INTENT:
            continue
        realised = [f for f in facts if f.claim.polarity == w.claim.polarity]
        rejected = [f for f in facts if f.claim.polarity != w.claim.polarity and f.since >= w.since]
        if realised or rejected:
            best = _strongest(realised or rejected)
            verb = "realised" if realised else "overtaken"
            w.set(Status.DEPRECATED, f"{verb}: now settled by {_cite(best)}")
            w.close_at(best if best.since >= w.since else w)
            w.superseded_by = [best.claim.id]
            continue
        blockers = prohibitions.get(_key(w.claim.subject), [])
        if blockers:
            w.blocked_by = sorted(b.claim.id for b in blockers)
            w.set(Status.PROPOSED, f"blocked by prohibition at {_cite(blockers[0])}")
        elif w.claim.modality is Modality.PLAN:
            w.set(Status.PLANNED, "accepted plan, not yet effective")
        else:
            w.set(Status.PROPOSED, "proposal, not accepted")


def _confidence(ws: list[_Work]) -> None:
    for w in ws:
        w.confidence = w.s
    for p in Polarity:
        valid = [w for w in ws if w.status is Status.VALID and w.claim.polarity == p]
        best: dict[SourceType, float] = {}
        for w in valid:
            best[w.claim.source_type] = max(best.get(w.claim.source_type, 0.0), w.s)
        combined = corroborate(best[t] for t in sorted(best))
        for w in valid:
            w.confidence = combined
            w.corroborated_by = sorted(v.claim.id for v in valid if v is not w)
            if len(best) > 1:
                w.reason += f"; corroborated by {len(best)} source types"


def _resolve_group(
    ws: list[_Work], prohibitions: dict[str, list[_Work]], as_of: date, cfg: Settings
) -> None:
    facts: list[_Work] = []
    for w in ws:
        if cfg.sources[w.claim.source_type].deprecated_by_path:
            w.set(Status.DEPRECATED, "path rule: api-specs/history/ and archive/ are superseded")
        elif w.claim.modality is Modality.PROHIBITION:
            w.set(Status.VALID, "active prohibition")
        elif w.claim.modality in _FACTUAL:
            facts.append(w)
    _supersede(facts, as_of, cfg)
    _rank_open(facts, cfg)
    _hypotheses(ws)
    _needs_corroboration(ws, cfg)
    _intent(ws, prohibitions)
    _confidence(ws)


def resolve(claims: Sequence[ClaimRecord], as_of: date, cfg: Settings) -> list[ResolvedClaim]:
    """Point-in-time: only claims observed on or before `as_of` exist."""
    visible = sorted(
        (c for c in claims if c.observed_at is None or c.observed_at <= as_of),
        key=lambda c: c.id,
    )
    work: dict[str, _Work] = {}
    groups: dict[str, list[ClaimRecord]] = defaultdict(list)
    for c in visible:
        if c.valid_from is None:
            w = work[c.id] = _Work(c, score(c, 1.0, cfg))
            w.set(Status.UNKNOWN, "no usable time signal")
            w.confidence = w.s
        else:
            triple = f"{_key(c.subject)}|{c.predicate}|{_key(c.object)}"
            groups[triple].append(c)

    for members in groups.values():
        for c in members:
            assert c.valid_from is not None
            against = [
                o.valid_from
                for o in members
                if o.polarity != c.polarity and o.modality in _FACTUAL and o.valid_from
            ]
            work[c.id] = _Work(c, score(c, freshness(c.valid_from, against, cfg), cfg))

    prohibitions: dict[str, list[_Work]] = defaultdict(list)
    for w in work.values():
        if w.claim.modality is Modality.PROHIBITION and w.claim.valid_from:
            prohibitions[_key(w.claim.subject)].append(w)

    for triple in sorted(groups):
        _resolve_group([work[c.id] for c in groups[triple]], prohibitions, as_of, cfg)

    return [
        ResolvedClaim(
            claim=w.claim,
            status=w.status or Status.UNKNOWN,
            reason=w.reason or "no rule applied",
            valid_to=w.valid_to,
            valid_to_precision=w.valid_to_precision,
            score=w.score,
            confidence=w.confidence,
            superseded_by=w.superseded_by,
            conflicts_with=w.conflicts_with,
            corroborated_by=w.corroborated_by,
            blocked_by=w.blocked_by,
        )
        for _, w in sorted(work.items())
    ]
