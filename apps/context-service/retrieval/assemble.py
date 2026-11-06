# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Resolved claims → the quality filter → the answer envelope.

Only statements with status VALID *and* confidence ≥ min_confidence reach `claims`.
Everything else that matched goes to `not_valid`, labelled with why, so an agent can
say "the wiki says X, but that is stale" instead of repeating X."""

import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import PurePosixPath

from models.answer import Answer, Citation, Conflict, EvidenceFilter, Statement, TimeFilter
from models.claim import ResolvedClaim, Span
from models.ontology import Polarity, Status, Verdict
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


def _relevance(question: set[str], members: Sequence[ResolvedClaim]) -> int:
    c = members[0].claim
    keys = _tokens(f"{c.subject.key} {c.object.key}")
    text = _tokens(" ".join(r.claim.evidence[0].excerpt for r in members))
    on_key, on_text = len(question & keys), len(question & text)
    return 3 * on_key + on_text if on_key or on_text >= 2 else 0


def _citation(span: Span, cfg: Settings) -> Citation:
    path = f"{cfg.corpus_dir}/{span.path}"
    lines = (span.start_line, span.end_line)
    excerpt = span.excerpt.replace("</untrusted_source", "&lt;/untrusted_source")
    via = None
    if span.path.endswith(".png"):
        stem = PurePosixPath(span.path).stem
        via = f"reviewed transcription {cfg.diagram_transcripts_dir}/{stem}.json"
    wrapped = f'<untrusted_source path="{path}" lines="{lines[0]}-{lines[1]}">{excerpt}</untrusted_source>'
    return Citation(path=path, lines=lines, excerpt=wrapped, via=via)


def _text(r: ResolvedClaim) -> str:
    c = r.claim
    neg = "NOT " if c.polarity is Polarity.NEGATES else ""
    return f"{c.subject.key} {neg}{c.predicate} {c.object.key}"


def _statement(
    members: list[ResolvedClaim],
    index: dict[str, ResolvedClaim],
    min_conf: float,
    cfg: Settings,
) -> Statement:
    ranked = sorted(members, key=lambda r: (-r.score.score, r.claim.id))
    top = ranked[0]
    usable = top.status is Status.VALID and top.confidence >= min_conf
    reason = top.reason
    if top.status is Status.VALID and not usable:
        reason = f"LOW_CONFIDENCE {top.confidence:.2f} < {min_conf:.2f}: {reason}"

    replaced = sorted({sid for r in members for sid in r.superseded_by if sid in index})
    successors = sorted((index[s] for s in replaced), key=lambda r: (-r.score.score, r.claim.id))
    closed = [r.valid_to for r in members if r.valid_to]
    starts = [r.claim.valid_from for r in members if r.claim.valid_from]
    return Statement(
        text=_text(top),
        subject=top.claim.subject,
        predicate=top.claim.predicate,
        object=top.claim.object,
        polarity=top.claim.polarity,
        verdict=Verdict.VALID if usable else Verdict.NOT_VALID,
        status=top.status,
        reason=reason,
        valid_from=min(starts) if starts else None,
        valid_to=max(closed) if closed else None,
        confidence=top.confidence,
        score=top.score,
        source_types=sorted({r.claim.source_type for r in members}),
        citations=[_citation(r.claim.evidence[0], cfg) for r in ranked],
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
        not_valid = [
            st.model_copy(update={"citations": st.citations[:1]}) for st in not_valid
        ]
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
    min_conf = cfg.min_confidence if evidence.min_confidence is None else evidence.min_confidence
    index = {r.claim.id: r for r in resolved}
    q = _tokens(question)

    triples: dict[str, list[ResolvedClaim]] = defaultdict(list)
    for r in resolved:
        c = r.claim
        triples[f"{c.subject.kind}:{c.subject.key}|{c.predicate}|{c.object.kind}:{c.object.key}"].append(r)

    scored = [(rel, key) for key, ms in triples.items() if (rel := _relevance(q, ms))]
    scored.sort(key=lambda x: (-x[0], x[1]))

    claims: list[Statement] = []
    not_valid: list[Statement] = []
    for _, key in scored[: cfg.max_statements]:
        buckets: dict[tuple[Polarity, Status], list[ResolvedClaim]] = defaultdict(list)
        for r in triples[key]:
            if r.status in time.status_in:
                buckets[(r.claim.polarity, r.status)].append(r)
        for bucket in sorted(buckets):
            st = _statement(buckets[bucket], index, min_conf, cfg)
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
        gaps.append(f"No VALID claim with confidence >= {min_conf:.2f} matches the question.")

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
