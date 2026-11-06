# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Resolved claims → the quality filter → the answer envelope.

Only statements with status VALID *and* confidence ≥ min_confidence reach `claims`.
Everything else that matched goes to `not_valid`, labelled with why, so an agent can
say "the wiki says X, but that is stale" instead of repeating X. Citations are pointers
(path, lines, hash); the text is fetched with resolve_span, never stored here."""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from models.answer import Answer, Citation, Conflict, EvidenceFilter, Statement, TimeFilter
from models.claim import ClaimRecord, ResolvedClaim, Span
from models.ontology import FilterCode, Polarity, SourceType, Status, Verdict
from settings import Settings

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "and", "for", "does", "did", "is", "are", "was", "what", "which", "who",
    "how", "still", "use", "uses", "using", "with", "from", "that", "this", "any",
    "our", "can", "should", "will", "has", "have", "about", "there", "it", "of",
    "to", "in", "on", "a", "an", "do", "we", "i",
}  # fmt: skip

DEGRADED_REASON = (
    "lexical match over resolved claims; the CQP planner and graph traversal "
    "are not implemented yet"
)


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in _STOP}


def _relevance(question: set[str], claim: ClaimRecord) -> int:
    # shortcut: entity keys only; Chunk text + BM25/vector replace this with the graph
    return len(question & _tokens(f"{claim.subject.key} {claim.object.key}"))


def _citation(span: Span, cfg: Settings) -> Citation:
    via = None
    if span.path.endswith(".png"):
        stem = PurePosixPath(span.path).stem
        via = f"reviewed transcription {cfg.diagram_transcripts_dir}/{stem}.json"
    return Citation(
        path=f"{cfg.corpus_dir}/{span.path}",
        lines=(span.start_line, span.end_line),
        hash=span.content_hash,
        via=via,
    )


def _text(r: ResolvedClaim) -> str:
    c = r.claim
    neg = "NOT " if c.polarity is Polarity.NEGATES else ""
    return f"{c.subject.key} {neg}{c.predicate} {c.object.key}"


@dataclass(frozen=True)
class Limits:
    """The answer-time quality bar, resolved once from the request and settings."""

    min_confidence: float
    min_source_types: int
    source_types: frozenset[SourceType] | None

    @classmethod
    def of(cls, evidence: EvidenceFilter, cfg: Settings) -> "Limits":
        conf, types = evidence.min_confidence, evidence.min_source_types
        return cls(
            min_confidence=cfg.min_confidence if conf is None else conf,
            min_source_types=cfg.min_source_types if types is None else types,
            source_types=frozenset(evidence.source_types) if evidence.source_types else None,
        )


def verdict(
    status: Status, confidence: float, source_types: int, limits: Limits
) -> FilterCode | None:
    """The one rule every answer is split on. None → VALID; else the first check failed.
    Order matters: a stale claim is reported as stale, not as weak."""
    if status is not Status.VALID:
        return FilterCode.STATUS
    if confidence < limits.min_confidence:
        return FilterCode.LOW_CONFIDENCE
    if source_types < limits.min_source_types:
        return FilterCode.SINGLE_SOURCE
    return None


def _explain(code: FilterCode | None, top: ResolvedClaim, kinds: int, limits: Limits) -> str:
    if code is FilterCode.LOW_CONFIDENCE:
        return f"LOW_CONFIDENCE {top.confidence:.2f} < {limits.min_confidence:.2f}: {top.reason}"
    if code is FilterCode.SINGLE_SOURCE:
        return f"SINGLE_SOURCE {kinds} < {limits.min_source_types} source types: {top.reason}"
    return top.reason


def _statement(
    members: list[ResolvedClaim],
    index: dict[str, ResolvedClaim],
    limits: Limits,
    cfg: Settings,
) -> Statement:
    ranked = sorted(members, key=lambda r: (-r.score.score, r.claim.id))
    top = ranked[0]
    kinds = len({r.claim.source_type for r in members})
    code = verdict(top.status, top.confidence, kinds, limits)
    shown = [
        r
        for r in ranked
        if limits.source_types is None or r.claim.source_type in limits.source_types
    ]

    replaced = sorted({sid for r in members for sid in r.superseded_by if sid in index})
    successors = sorted((index[s] for s in replaced), key=lambda r: (-r.score.score, r.claim.id))
    closed = [(r.valid_to, r.valid_to_precision) for r in members if r.valid_to]
    starts = [r.claim.valid_from for r in members if r.claim.valid_from]
    return Statement(
        text=_text(top),
        subject=top.claim.subject,
        predicate=top.claim.predicate,
        object=top.claim.object,
        polarity=top.claim.polarity,
        verdict=Verdict.VALID if code is None else Verdict.NOT_VALID,
        status=top.status,
        filtered_by=code,
        reason=_explain(code, top, kinds, limits),
        valid_from=min(starts) if starts else None,
        valid_to=max(closed)[0] if closed else None,
        valid_to_precision=max(closed)[1] if closed else None,
        confidence=top.confidence,
        score=top.score,
        source_types=sorted({r.claim.source_type for r in members}),
        citations=[_citation(r.claim.evidence[0], cfg) for r in shown],
        superseded_by=[_citation(r.claim.evidence[0], cfg) for r in successors[:2]],
    )


def _within_budget(
    claims: list[Statement], not_valid: list[Statement], budget: int, render
) -> tuple[list[Statement], list[Statement], bool]:
    """Spend order from docs/06-retrieval.md#context-budget: not-valid detail goes
    first, then extra citations, then not-valid entries, then the weakest valid ones."""

    def fits() -> bool:
        return len(render(claims, not_valid)) // 4 <= budget

    truncated = False

    def one_citation(st: Statement) -> Statement:
        return st.model_copy(update={"citations": st.citations[:1], "superseded_by": []})

    if not fits():
        truncated = True
        not_valid = [st.model_copy(update={"citations": st.citations[:1]}) for st in not_valid]
    if not fits():
        claims = [st.model_copy(update={"citations": st.citations[:1]}) for st in claims]
    if not fits():
        not_valid = [one_citation(st) for st in not_valid]
    while not fits() and not_valid:
        not_valid = not_valid[:-1]
    while not fits() and len(claims) > 1:
        claims = claims[:-1]
    return claims, not_valid, truncated


def assemble(
    question: str,
    resolved: Sequence[ResolvedClaim],
    as_of: date,
    time: TimeFilter,
    evidence: EvidenceFilter,
    cfg: Settings,
) -> Answer:
    limits = Limits.of(evidence, cfg)
    index = {r.claim.id: r for r in resolved}
    q = _tokens(question)

    triples: dict[str, list[ResolvedClaim]] = defaultdict(list)
    for r in resolved:
        c = r.claim
        triple = f"{c.subject.kind}:{c.subject.key}|{c.predicate}|{c.object.kind}:{c.object.key}"
        triples[triple].append(r)

    scored = [(rel, key) for key, ms in triples.items() if (rel := _relevance(q, ms[0].claim))]
    scored.sort(key=lambda x: (-x[0], x[1]))

    claims: list[Statement] = []
    not_valid: list[Statement] = []
    for _, key in scored[: cfg.max_statements]:
        buckets: dict[tuple[Polarity, Status], list[ResolvedClaim]] = defaultdict(list)
        for r in triples[key]:
            if r.status in time.status_in:
                buckets[(r.claim.polarity, r.status)].append(r)
        for bucket in sorted(buckets):
            members = buckets[bucket]
            if limits.source_types and not any(
                r.claim.source_type in limits.source_types for r in members
            ):
                continue
            st = _statement(members, index, limits, cfg)
            (claims if st.verdict is Verdict.VALID else not_valid).append(st)

    claims.sort(key=lambda s: -s.confidence)
    conflicts = _conflicts(claims + not_valid, resolved)

    def render(cs: list[Statement], nv: list[Statement]) -> str:
        return Answer(
            question=question, as_of=as_of, answer="", claims=cs, not_valid=nv,
            conflicts=conflicts, gaps=[], degraded=True,
            degraded_reason=DEGRADED_REASON, truncated=False,
        ).model_dump_json()  # fmt: skip

    claims, not_valid, truncated = _within_budget(claims, not_valid, cfg.token_budget, render)

    gaps: list[str] = []
    if not scored:
        gaps.append("No claim in the index matches the question.")
    elif not claims:
        gaps.append(
            f"No VALID claim with confidence >= {limits.min_confidence:.2f} "
            f"from >= {limits.min_source_types} source type(s) matches the question."
        )

    summary = "; ".join(st.text for st in claims[:3]) if claims else "No valid evidence found."
    return Answer(
        question=question,
        as_of=as_of,
        answer=summary,
        claims=claims,
        not_valid=not_valid,
        conflicts=conflicts,
        gaps=gaps,
        degraded=True,
        degraded_reason=DEGRADED_REASON,
        truncated=truncated,
    )


def _conflicts(statements: list[Statement], resolved: Sequence[ResolvedClaim]) -> list[Conflict]:
    texts = {r.claim.id: _text(r) for r in resolved}
    seen: set[tuple[str, ...]] = set()
    out: list[Conflict] = []
    shown = {st.text for st in statements}
    for r in resolved:
        if not r.conflicts_with or _text(r) not in shown:
            continue
        pair = tuple(sorted({_text(r), *(texts[i] for i in r.conflicts_with if i in texts)}))
        if pair not in seen:
            seen.add(pair)
            out.append(Conflict(statements=list(pair), reason=r.reason))
    return out
