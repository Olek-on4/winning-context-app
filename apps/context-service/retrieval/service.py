"""The one service layer: plan -> validate -> compile -> execute -> assemble.

Assembled claims are pointers (path, lines, hash), never prose. The text is verified
against the corpus at read time, so a stale graph cannot produce a false citation.
"""

from __future__ import annotations

import re

from graph.resolver import Status
from retrieval import hybrid, planner
from retrieval.cqp import CQP, MAX_NODES, MAX_SPANS, Anchor, Intent, compile_semantic, validate_plan
from retrieval.cqp import compile as compile_cqp
from settings import (
    DETAIL_CLAIM_FIELDS,
    DETAIL_DEFAULT,
    DETAIL_EXCERPT_CHARS,
    DETAIL_LEVELS,
    EFFORT_EVIDENCE,
    EFFORT_MAX,
    EFFORT_MAX_RESULTS,
    EFFORT_MIN_RESULTS,
    EFFORT_SEMANTIC_K,
    EVIDENCE_MIN_CHARS,
    EVIDENCE_MIN_COSINE,
    EVIDENCE_MIN_RATIO,
    EVIDENCE_TEXT_LIMIT,
    TOKEN_BUDGET,
    VOCAB_RESOLVE,
)
from sources import image_size

_STATUS_RANK = {
    Status.VALID.value: 0,
    Status.DISPUTED.value: 1,
    Status.PLANNED.value: 2,
    Status.PROPOSED.value: 3,
    Status.DEPRECATED.value: 4,
    Status.UNKNOWN.value: 5,
}

_CLAIM_FIELDS = (
    "statement",
    "status",
    "valid_from",
    "valid_to",
    "confidence",
    "superseded_by",
    "citations",
)

# Everything a claim dict may carry, base fields first. `detail` decides what a caller
# actually receives; the internal dict keeps the union so no level needs a second query.
_EXTRA_FIELDS = (
    "id",
    "subject",
    "predicate",
    "polarity",
    "why_not_valid",
    "extractor",
    "extractor_version",
    "observed_at",
    "modality",
    "authority",
)


# Retrieval is untrusted input; this is the deterministic half of the defence (07 #Security).
# It flags, it never strips: a seeded injection in a repo is itself a finding.
_INJECTION = re.compile(
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions"
    r"|disregard\s+(all\s+)?(previous|prior|above)"
    r"|you\s+are\s+now\s+(a|an|the)\b"
    r"|^\s*(system|assistant)\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def _suspicious(text: str) -> bool:
    return bool(_INJECTION.search(text))


def _untrusted(path: str, text: str) -> str:
    """Corpus bytes are data, never instructions: mark them at the boundary.

    AGENTS.md invariant 3 and [07](../docs/07-api-and-mcp.md) both require retrieved text to
    arrive inside `<untrusted_source>` delimiters, because the same string lands in an LLM's
    context window. The tag carries the path so a reader can resolve it again.
    """
    return f'<untrusted_source path="{path}">\n{text}\n</untrusted_source>'


def _detail(level: str | None) -> str:
    """Unreadable detail is a caller error, not a reason to answer with no claims."""
    if level is None:
        return DETAIL_DEFAULT
    text = str(level).strip().lower()
    return text if text in DETAIL_LEVELS else DETAIL_DEFAULT


def _why_not_valid(claim: dict) -> str | None:
    """One line saying what is wrong with a claim that is not current, or None if it is."""
    status = claim.get("status")
    if status == Status.VALID.value:
        return None
    if status == Status.DEPRECATED.value:
        by = claim.get("superseded_by")
        until = claim.get("valid_to")
        if by and until:
            return f"superseded by {by} on {until}"
        return f"superseded by {by}" if by else "superseded, but the replacement is not in the graph"
    if status == Status.DISPUTED.value:
        return "another source contradicts it and neither has been resolved"
    if status == Status.PLANNED.value:
        return "planned, not in effect"
    if status == Status.PROPOSED.value:
        return "proposed, not approved"
    return "no current evidence supports it"


# The corpus is the dictionary: a question token is a word worth anchoring on only if
# some entity key contains it. `hits` orders candidates most-specific first, which is
# the IDF effect without needing a stopword list for whatever language the corpus is in.
# Kind is deliberately NOT taken from here: one key can be a Service and a Table at
# once, and the predicate filter already separates those cases.
_ATTEST = """
UNWIND $tokens AS t
MATCH (e:Entity)
WHERE toLower(e.key) CONTAINS toLower(t)
RETURN t AS token, count(*) AS hits
ORDER BY hits ASC, token ASC
"""


class ContextService:
    def __init__(self, driver, corpus_root):
        """`corpus_root` is a Path (single tree) or a `SpanStore` (any number of roots)."""
        from pathlib import Path as _Path

        from sources import SpanStore

        self.driver = driver
        if isinstance(corpus_root, SpanStore):
            self.spans = corpus_root
        else:
            from sources import discover

            self.spans = SpanStore(discover([_Path(corpus_root)]))

    def _resolved(self, plan: CQP, question: str) -> CQP:
        """Anchors and predicates from the embedded vocabulary, else the attested plan.

        The embedding proposes and the graph disposes: keys come from a set built out of
        `Entity` nodes, and predicates from the closed gloss table, so nothing here can
        invent an identifier. Any failure — no model, no index, an empty match — falls
        back to the deterministic attestation below.
        """
        from graph import vocab

        if not VOCAB_RESOLVE:
            return self._attested(plan)
        resolved = vocab.resolve(self.driver, question, embed=hybrid._embed)
        if resolved is None:
            return self._attested(plan)
        keys, _ = resolved
        if not keys:
            return self._attested(plan)
        # Only the anchors come from the embedding. A predicate is a member of a closed
        # enum and an OR-filter over it, so a wrong guess silently deletes the right
        # answer: "how do people and accounts connect" became AUTHENTICATES_VIA and lost
        # every claim. Predicates therefore stay with the declared ontology cues.
        return plan.model_copy(
            update={"anchors": [Anchor(kind="ANY", key=key, match="exact") for key in keys[:3]]}
        )

    def _attested(self, plan: CQP) -> CQP:
        """Keep only the anchors whose token actually occurs in an entity key.

        This replaces a stopword list: "between" is not dropped because English says it
        carries no content, it is dropped because no entity in this corpus contains it.
        A new corpus therefore needs no new word list.
        """
        keys = [anchor.key for anchor in plan.anchors if anchor.key]
        if not keys:
            return plan
        try:
            rows = _execute(self.driver, _ATTEST, {"tokens": keys})
            # Keep the most specific words only: a token that names a handful of entities
            # identifies a subject, a token that names most of them ("service") identifies
            # nothing and only widens the query. That is IDF by another name, computed
            # from this corpus instead of from a list of English stopwords.
            floor = rows[0]["hits"] if rows else 0
            kept = [
                Anchor(kind="ANY", key=row["token"], match="exact")
                for row in rows
                if row["hits"] <= max(floor + 1, floor * 2)
            ][:3]
        except Exception:
            # Attestation is a refinement of the plan, never a reason to fail an answer.
            return plan
        if not kept:
            # Nothing attested: hand the whole question to the text search instead of
            # pretending a word we cannot find is an identifier.
            question = " ".join(filter(None, (a.key or a.text for a in plan.anchors)))
            kept = [Anchor(kind="ANY", text=question[:200] or "?", match="hybrid")]
        return plan.model_copy(update={"anchors": kept})

    def plan(self, question: str, *, intent: str | None = None) -> dict:
        """The query plan, inspectable and unexecuted.

        Stays a pure CQP on purpose: `answer()` feeds this dict back through
        `CQP.model_validate`, and that model forbids extra fields, so provenance cannot
        ride here without breaking every answer.
        """
        return planner.plan(question, intent=intent).model_dump()

    def explain(self, question: str, *, intent: str | None = None) -> dict:
        """The plan plus its provenance: `source` is "model" or "deterministic".

        A model is not always consulted - ADR-0005 skips it when the question names an
        identifier - so "no model ran" and "the model agreed" must not look identical.
        """
        trace: dict[str, str] = {}
        plan = planner.plan(question, intent=intent, trace=trace)
        return {**plan.model_dump(), **trace}

    def execute(self, plan: dict) -> dict:
        """Run a caller-supplied CQP.

        Cypher still comes from the template library: the plan is validated and compiled
        here, so a caller can choose what to ask but never how it is queried (ADR-0003).
        """
        try:
            validated = validate_plan(plan)
            cypher, params = compile_cqp(validated)
            rows = _execute(self.driver, cypher, params)
        except Exception as exc:
            return _envelope(
                "No answer: the query plan was rejected.",
                [],
                [],
                [f"Execute failed ({type(exc).__name__})."],
                True,
            )
        claims, conflicts, gaps = self._assemble(rows, validated)
        return _envelope(_answer_text(claims), claims, conflicts, _dedupe(gaps), False)

    def entity(self, kind: str, key: str) -> dict:
        """Everything asserted about one identity, by exact match rather than relevance."""
        plan = CQP(intent=Intent.LOOKUP, anchors=[Anchor(kind=kind, key=key, match="exact")])
        return self.execute(plan.model_dump())

    def sources(self) -> list[dict]:
        """Every indexed root and the chunks it contributed — the index's own inventory."""
        rows = _execute(
            self.driver,
            "MATCH (s:Source) OPTIONAL MATCH (c:Chunk)-[:IN]->(s) "
            "RETURN s.path AS path, count(c) AS chunks ORDER BY path",
            {},
        )
        return [{"path": row["path"], "chunks": row["chunks"]} for row in rows]

    def index_status(self) -> dict:
        """Node counts, so an operator can tell an empty index from an empty answer."""
        rows = _execute(
            self.driver,
            "RETURN count{(:Claim)} AS claims, count{(:Chunk)} AS chunks, "
            "count{(:Source)} AS sources",
            {},
        )
        return dict(rows[0]) if rows else {"claims": 0, "chunks": 0, "sources": 0}

    def answer(
        self,
        question: str,
        *,
        intent: str | None = None,
        as_of: str | None = None,
        status_in: list[str] | None = None,
        token_budget: int = TOKEN_BUDGET,
        effort: int | None = None,
        detail: str | None = None,
    ) -> dict:
        level = _detail(detail)
        gaps: list[str] = []
        degraded = False

        try:
            base = self._resolved(CQP.model_validate(self.plan(question, intent=intent)), question)
        except Exception as exc:
            return _envelope(
                "No answer: the planner is unavailable.",
                [],
                [],
                [f"Planner failed ({type(exc).__name__})."],
                True,
                detail=level,
            )

        try:
            plan = validate_plan(_overridden(base, as_of, status_in, token_budget, effort).model_dump())
        except Exception:
            gaps.append("Invalid query options were ignored.")
            plan = validate_plan(base.model_dump())

        try:
            cypher, params = compile_cqp(plan)
        except Exception as exc:
            return _envelope(
                "No answer: the query plan was rejected.",
                [],
                [],
                gaps + [f"Compiler rejected the plan ({type(exc).__name__})."],
                True,
                detail=level,
            )

        try:
            rows = _execute(self.driver, cypher, params)
            graph_error: str | None = None
        except Exception as exc:
            rows = []
            degraded = True
            graph_error = f"Graph query failed ({type(exc).__name__})."

        claims, conflicts, assemble_gaps = self._assemble(rows, plan, level)
        gaps.extend(assemble_gaps)
        if graph_error:
            gaps.append(graph_error)

        # Effort, not luck: a question that names nothing may still be answerable by
        # meaning. The promise is counted in claims, and the gates already ran, so this
        # widens recall only - it cannot promote a weaker answer to a stronger one.
        target = EFFORT_MIN_RESULTS[min(plan.effort, EFFORT_MAX)]
        if len(claims) < target:
            extra = self._semantic(plan, question)
            if extra:
                more, more_conflicts, more_gaps = self._assemble(extra, plan, level)
                before = len(claims)
                claims = _merge_claims(claims, more)
                conflicts = _merge_claims(conflicts, more_conflicts)
                gaps.extend(more_gaps)
                added = len(claims) - before
                if added:
                    gaps.append(
                        f"Widened by meaning: {added} more claim(s) from the embedded statements."
                    )

        # Passages are fetched at every level above 0: a corpus is mostly prose that no
        # extractor turned into a triple, and a query that only reads claims silently
        # discards it. One search per request (#78), so this is the only place it happens.
        # `detail=low` returns no passages, so it does not pay for the search either.
        evidence: list[dict] = []
        if level != "low" and EFFORT_EVIDENCE[min(plan.effort, EFFORT_MAX)]:
            chunks, chunk_degraded, channel_status = _hybrid(self.driver, question)
            degraded = degraded or chunk_degraded
            failed = sorted(name for name, state in channel_status.items() if state == "error")
            if failed:
                gaps.append(f"Search channel unavailable: {', '.join(failed)}.")
            evidence = self._passages(chunks, plan, question)
            if evidence:
                gaps.append(
                    f"{len(evidence)} passage(s) returned as evidence, not as claims: "
                    "verbatim corpus text, cited by line."
                )
            elif not claims and chunks:
                gaps.append("Chunks matched but none survived verification.")
            elif not claims and any(state in {"ok", "empty"} for state in channel_status.values()):
                # Only when both channels ran cleanly: a dead channel already said so, and
                # two contradictory gap sets is the bug #78 removed.
                gaps.append("No claims matched the plan and no passage survived verification.")

        answer = _answer_text(claims)
        claims, conflicts, evidence, answer, truncated = _spend_budget(
            claims, conflicts, answer, plan.output.token_budget, evidence, level
        )
        if truncated:
            degraded = True
            gaps.insert(0, f"Response truncated to {plan.output.token_budget} tokens.")

        plan_echo = {
            "intent": plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
            "effort": min(plan.effort, EFFORT_MAX),
            "as_of": plan.time.as_of,
            "status_in": list(plan.time.status_in),
            "token_budget": plan.output.token_budget,
            "detail": level,
        }
        body = _envelope(
            answer, claims, conflicts, _dedupe(gaps), degraded, evidence, level, plan_echo
        )
        body["claims"] = [_project(claim, level) for claim in body["claims"]]
        return body

    def _semantic(self, plan: CQP, question: str) -> list[dict]:
        """Claims whose embedded statement is close to the question, or [] at effort 0.

        Never raises: an absent model, an unbuilt index or no vector is a quieter answer,
        never a failed one.
        """
        level = min(plan.effort, EFFORT_MAX)
        k = EFFORT_SEMANTIC_K[level]
        if not k:
            return []
        try:
            vector = hybrid._embed(question)
            if not vector:
                return []
            cypher, params = compile_semantic(plan, k, vector, EFFORT_MAX_RESULTS[level])
            return _execute(self.driver, cypher, params)
        except Exception:
            return []

    def _passages(self, chunks: list[dict], plan: CQP, question: str) -> list[dict]:
        """Verified passages from chunk hits: the layer under claims.

        A passage is corpus text, so it is held to the same standard as a citation - the
        file hash and the line range must match - and it is never given a status, because
        "the corpus says this here" is not "this is true". Text is trimmed, not summarised:
        a paraphrase would be our words pretending to be theirs.
        """
        level = min(plan.effort, EFFORT_MAX)
        limit = EFFORT_EVIDENCE[level]
        if not limit:
            return []
        out: list[dict] = []
        seen: set[tuple[str, int, int]] = set()
        for chunk in chunks:
            if len(out) >= limit:
                break
            lines = chunk.get("lines") or []
            region = chunk.get("region")
            if len(lines) != 2 and not region:
                continue
            probe = {"path": chunk["path"], "hash": chunk.get("hash") or ""}
            if region:
                # An image has no line range: the rectangle is the citation.
                probe.update({"start_line": 1, "end_line": 1, "region": region})
            else:
                probe.update({"start_line": lines[0], "end_line": lines[1]})
            verified, _ = self._verify([probe], 1)
            if not verified:
                continue
            if not _is_prose(chunk.get("text") or ""):
                continue
            if not _is_relevant(chunk, question):
                continue
            key = (verified[0]["path"], verified[0]["lines"][0], verified[0]["lines"][1],
                   tuple(verified[0].get("region") or ()))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "path": verified[0]["path"],
                    "lines": [lines[0], lines[1]],
                    "hash": verified[0]["hash"],
                    "heading": chunk.get("heading") or "",
                    "text": _untrusted(
                        verified[0]["path"], str(chunk.get("text") or "")[:EVIDENCE_TEXT_LIMIT]
                    ),
                    "score": chunk.get("score"),
                    "via": chunk.get("via") or "",
                    "suspicious": _suspicious(str(chunk.get("text") or "")),
                    # An image passage is cited by its rectangle; the drawer needs it.
                    **({"region": verified[0]["region"]} if verified[0].get("region") else {}),
                }
            )
        return out

    def _assemble(
        self, rows: list[dict], plan: CQP, detail: str = DETAIL_DEFAULT
    ) -> tuple[list[dict], list[dict], list[str]]:
        gaps: list[str] = []
        entries: dict[str, dict] = {}
        max_spans = min(plan.evidence.max_spans_per_claim, MAX_SPANS)

        for row in rows:
            confidence = _number(row.get("confidence"))
            if confidence < plan.evidence.min_confidence:
                continue
            statement = _statement(row)
            status = str(row.get("status") or Status.UNKNOWN.value)
            if status not in _STATUS_RANK:
                status = Status.UNKNOWN.value
            citations, citation_gaps = self._verify(
                list(row.get("citations") or []), max_spans, detail
            )
            gaps.extend(citation_gaps)
            # Same triple, polarity and status is one fact with several citations.
            # Opposite polarity is a disagreement and must stay two rows.
            key = (
                f"{row.get('subject')}|{row.get('predicate')}|{row.get('object')}"
                f"|{row.get('polarity')}|{status}"
            )
            if plan.evidence.require_citations and not citations:
                gaps.append(f"Dropped claim {key}: no verifiable citation.")
                continue

            entry = entries.get(key)
            if entry is None:
                entries[key] = {
                    # The graph's claim id: `superseded_by` must name a claim, and a claim
                    # id is the only durable name for one (#80).
                    "id": str(row.get("id") or key),
                    "subject": str(row.get("subject") or ""),
                    "predicate": str(row.get("predicate") or ""),
                    "polarity": str(row.get("polarity") or "ASSERTS"),
                    "statement": statement,
                    "status": status,
                    "valid_from": _iso(row.get("valid_from")),
                    "valid_to": _iso(row.get("valid_to")),
                    "confidence": round(confidence, 4),
                    "superseded_by": _text_or_none(row.get("superseded_by")),
                    "citations": citations,
                    "extractor": _text_or_none(row.get("extractor")),
                    "extractor_version": _text_or_none(row.get("extractor_version")),
                    "observed_at": _iso(row.get("observed_at")),
                    "modality": _text_or_none(row.get("modality")),
                    "authority": row.get("authority"),
                }
                continue

            entry["confidence"] = max(entry["confidence"], round(confidence, 4))
            entry["id"] = min(entry["id"], str(row.get("id") or entry["id"]))
            if entry["valid_from"] is None:
                entry["valid_from"] = _iso(row.get("valid_from"))
            if entry["valid_to"] is None:
                entry["valid_to"] = _iso(row.get("valid_to"))
            if entry["superseded_by"] is None:
                entry["superseded_by"] = _text_or_none(row.get("superseded_by"))
            known = {(c["path"], tuple(c["lines"])) for c in entry["citations"]}
            for citation in citations:
                if (citation["path"], tuple(citation["lines"])) not in known:
                    entry["citations"].append(citation)

        claims = sorted(
            entries.values(),
            key=lambda e: (
                _STATUS_RANK.get(e["status"], len(_STATUS_RANK)),
                -e["confidence"],
                e["statement"],
                e["id"],
            ),
        )[: min(plan.traverse.max_nodes, MAX_NODES)]

        if plan.time.as_of:
            claims = _as_of_view(claims, plan.time.as_of)

        _link_superseded(claims)
        conflicts = _conflicts(claims) if plan.output.include_conflicts else []

        projected = [_project(claim, detail) for claim in claims]
        return projected, conflicts, gaps

    def _verify(
        self, citations: list, max_spans: int, detail: str = DETAIL_DEFAULT
    ) -> tuple[list[dict], list[str]]:
        out: list[dict] = []
        gaps: list[str] = []
        seen: set[tuple] = set()

        for item in citations[:max_spans]:
            if not isinstance(item, dict):
                gaps.append("Citation was not a mapping.")
                continue
            path = str(item.get("path") or "")
            start, end = item.get("start_line"), item.get("end_line")
            region = item.get("region")
            if region is not None:
                region = [int(v) for v in region]
                if len(region) != 4:
                    gaps.append(f"Citation {path} has a malformed region.")
                    continue
                start, end = 1, 1
            if not path or start is None or end is None:
                gaps.append("Citation is missing a path or line range.")
                continue
            try:
                start, end = int(start), int(end)
            except (TypeError, ValueError):
                gaps.append(f"Citation {path} has non-numeric lines.")
                continue

            try:
                if region is not None:
                    # Bounds before bytes: a rectangle outside the image is not evidence
                    # of anything, whatever the digest says.
                    width, height = image_size(self.spans.resolve(path))
                    x, y, w, h = region
                    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                        gaps.append(f"Citation {path}@{region} escapes the {width}x{height} image.")
                        continue
                body = b""
                if region is None:
                    body = self.spans.read(path, start, end)
                digest = self.spans.hash(path)
            except FileNotFoundError:
                gaps.append(f"Citation {path} is outside every registered root.")
                continue
            except PermissionError:
                gaps.append(f"Citation {path} escapes its root.")
                continue
            except ValueError as exc:
                gaps.append(f"Citation {path}:{start}-{end} is outside the file ({exc}).")
                continue
            stored = str(item.get("hash") or "").strip()
            if stored and not (digest.startswith(stored) or stored.startswith(digest)):
                gaps.append(f"Citation {path}:{start}-{end} failed hash verification.")
                continue
            key = (path, start, end, tuple(region or ()))
            if key in seen:
                continue
            seen.add(key)
            entry: dict = {"path": path, "lines": [start, end], "hash": stored or digest}
            if region is not None:
                entry["region"] = region
            elif detail == "high":
                # `high` quotes the cited lines so an agent need not spend a second call.
                entry["suspicious"] = _suspicious(body.decode("utf-8", "replace"))
                entry["excerpt"] = _untrusted(
                    path, body.decode("utf-8", "replace")[:DETAIL_EXCERPT_CHARS]
                )
            out.append(entry)

        return out, gaps

def _execute(driver, cypher: str, params: dict) -> list[dict]:
    with driver.session() as session:
        result = session.run(cypher, **params)
        return [dict(record) for record in result]


def _hybrid(driver, question: str) -> tuple[list[dict], bool, dict[str, str]]:
    # The graph call failed, so the same driver may be unavailable too; degrade quietly.
    try:
        return hybrid.search(driver, question)
    except Exception:
        return [], True, {}


def _overridden(base: CQP, as_of, status_in, token_budget, effort=None) -> CQP:
    """Apply the caller's knobs. An unreadable effort is ignored, never fatal."""
    updates: dict = {}
    if effort is not None:
        try:
            level = int(effort)
        except (TypeError, ValueError):
            level = base.effort
        updates["effort"] = max(0, min(level, EFFORT_MAX))
    time_updates: dict = {}
    if as_of is not None:
        time_updates["as_of"] = as_of
    if status_in is not None:
        time_updates["status_in"] = list(status_in)
    if time_updates:
        updates["time"] = base.time.model_copy(update=time_updates)
    try:
        budget = int(token_budget)
    except (TypeError, ValueError):
        budget = base.output.token_budget
    if budget != base.output.token_budget:
        updates["output"] = base.output.model_copy(update={"token_budget": budget})
    return base.model_copy(update=updates)


def _statement(row: dict) -> str:
    subject = str(row.get("subject") or "unknown")
    predicate = str(row.get("predicate") or "RELATES_TO")
    negated = str(row.get("polarity") or "ASSERTS").upper() == "NEGATES"
    parts = [subject, "NOT" if negated else "", predicate]
    obj = row.get("object")
    if obj is not None and str(obj):
        parts.append(str(obj))
    return " ".join(part for part in parts if part)


def _as_of_view(claims: list[dict], as_of: str) -> list[dict]:
    """Point in time: a claim superseded later was still true then, and a claim that
    starts later did not exist. Status is recomputed, never trusted from the snapshot."""
    view: list[dict] = []
    for claim in claims:
        started = claim.get("valid_from")
        if not started or started > as_of:
            # Undated claims cannot be placed on a timeline, so they are not shown as if
            # they existed at that date. They remain in the default (current) view.
            continue
        ended = claim.get("valid_to")
        if ended and ended <= as_of:
            continue
        if claim["status"] == Status.DEPRECATED.value:
            claim = {**claim, "status": Status.VALID.value, "superseded_by": None}
        view.append(claim)
    return view


def _link_superseded(claims: list[dict]) -> None:
    """Point a superseded claim at its successor by claim id — the one representation.

    Rule, mirrored by the TIMELINE template so both agree (#80): candidates are claims
    with the same subject and predicate and a later `valid_from`; the earliest
    `valid_from` wins, and ties break on the lowest claim id. A citation path is not a
    claim: several claims share one file, so it identifies no successor.
    """
    valids = [claim for claim in claims if claim["status"] == Status.VALID.value]
    for claim in claims:
        if claim["status"] != Status.DEPRECATED.value or claim["superseded_by"]:
            continue
        if not claim["valid_from"]:
            continue
        later = [
            winner
            for winner in valids
            if winner["subject"] == claim["subject"]
            and winner["predicate"] == claim["predicate"]
            and winner["valid_from"]
            and winner["valid_from"] > claim["valid_from"]
        ]
        if not later:
            continue
        winner = min(later, key=lambda w: (w["valid_from"], w["id"]))
        claim["superseded_by"] = winner["id"]


def _conflicts(claims: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for claim in claims:
        if claim["status"] == Status.DISPUTED.value:
            groups.setdefault((claim["subject"], claim["predicate"]), []).append(claim)

    out: list[dict] = []
    for key in sorted(groups):
        group = groups[key]
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                if left["polarity"] == right["polarity"]:
                    continue
                if left["statement"] == right["statement"]:
                    continue
                a, b = sorted((left["statement"], right["statement"]))
                out.append(
                    {"a": a, "b": b, "note": "Sources disagree; the resolver found no winner."}
                )
    out.sort(key=lambda conflict: (conflict["a"], conflict["b"]))
    return out


_ANSWER_LABEL = {
    Status.DISPUTED.value: "Disputed",
    Status.PLANNED.value: "Planned",
    Status.PROPOSED.value: "Proposed",
    Status.UNKNOWN.value: "Unconfirmed",
}


def _answer_text(claims: list[dict]) -> str:
    valid = [claim for claim in claims if claim["status"] == Status.VALID.value]
    deprecated = [claim for claim in claims if claim["status"] == Status.DEPRECATED.value]
    parts: list[str] = []
    if valid:
        parts.append("; ".join(claim["statement"] for claim in valid[:3]))
    if deprecated:
        parts.append("Superseded: " + "; ".join(claim["statement"] for claim in deprecated[:2]))
    if not parts and claims:
        # Nothing current or superseded matched, but rows did: name them, labelled. A miss
        # message beside a non-empty `claims` array tells the reader the opposite of the truth.
        grouped: dict[str, list[str]] = {}
        for claim in claims:
            label = _ANSWER_LABEL.get(claim["status"], claim["status"].capitalize())
            grouped.setdefault(label, []).append(claim["statement"])
        parts = [f"{label}: " + "; ".join(statements[:2]) for label, statements in grouped.items()][:2]
    if not parts:
        return "No validated claims matched the question."
    text = ". ".join(parts)
    return text[:1].upper() + text[1:] + "."


def _spend_budget(
    claims: list[dict],
    conflicts: list[dict],
    answer: str,
    budget: int,
    evidence: list[dict] | None = None,
    detail: str = DETAIL_DEFAULT,
) -> tuple[list[dict], list[dict], list[dict], str, bool]:
    """Spend in documented order: answer, one citation per claim, conflicts, extras.

    The answer is spent first and truncated to fit, so an oversized answer can no longer
    run over the budget and still appear in full (#76). Returns the possibly shortened
    answer; `truncated` is True whenever anything was cut, so the caller can say so.
    """
    answer, truncated = _truncate_answer(answer, budget)
    remaining = max(int(budget), 1) - _tokens(answer)
    paired: list[tuple[dict, dict]] = []

    for claim in claims:
        cost = _claim_cost(claim, 1)
        if cost > remaining:
            truncated = True
            continue
        remaining -= cost
        paired.append((claim, dict(claim, citations=claim["citations"][:1])))

    kept_conflicts: list[dict] = []
    for conflict in conflicts:
        cost = (
            _tokens(conflict["a"]) + _tokens(conflict["b"]) + _tokens(conflict["note"]) + 6
        )
        if cost > remaining:
            truncated = True
            break
        remaining -= cost
        kept_conflicts.append(conflict)

    # `low` returns one citation per claim, so it must not pay for the others.
    for original, kept in paired:
        if detail == "low":
            break
        for citation in original["citations"][1:]:
            cost = _claim_cost({"statement": "", "citations": [citation]}, 1) - 7
            if cost > remaining:
                truncated = True
                break
            remaining -= cost
            kept["citations"].append(citation)

    kept_evidence: list[dict] = []
    # `low` returns no passages, so it must not spend budget reserving them.
    for passage in [] if detail == "low" else (evidence or []):
        cost = _tokens(str(passage.get("text") or "")) + _tokens(str(passage.get("path") or "")) + 4
        if cost > remaining:
            truncated = True
            break
        remaining -= cost
        kept_evidence.append(passage)

    return [kept for _, kept in paired], kept_conflicts, kept_evidence, answer, truncated


def _truncate_answer(answer: str, budget: int) -> tuple[str, bool]:
    """Cut the answer to `budget` tokens, ending on an ellipsis; never mid-word."""
    limit = max(int(budget), 1)
    if _tokens(answer) <= limit:
        return answer, False
    room = max(0, limit * 4 - 4)  # `_tokens` is ceil(len / 4): stay strictly inside
    cut = answer[:room]
    spaced = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return f"{spaced.rstrip(' .,;:')}…", True


def _claim_cost(claim: dict, citation_count: int) -> int:
    cost = _tokens(claim["statement"]) + 6
    for citation in claim["citations"][:citation_count]:
        cost += _tokens(citation["path"]) + 4
        if citation.get("excerpt"):
            # `_tokens` already charges 1 for the empty case; add the rest of the quote.
            cost += _tokens(citation["excerpt"]) - 1
    return cost


def _tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _project(claim: dict, detail: str) -> dict:
    """The claim as the caller asked to see it: base fields, then the level's extras."""
    body = {field: claim.get(field) for field in _CLAIM_FIELDS}
    if detail != "low":
        body["why_not_valid"] = _why_not_valid(claim)
    for field in DETAIL_CLAIM_FIELDS[detail]:
        if field in claim:
            body[field] = claim[field]
    if detail == "low":
        # One citation is enough to check the claim; the rest are bytes the caller did not buy.
        body["citations"] = list(claim.get("citations") or [])[:1]
    if detail != "high":
        body["citations"] = [
            {k: v for k, v in citation.items() if k != "excerpt"}
            for citation in body.get("citations") or []
        ]
    return body


def _envelope(
    answer: str,
    claims: list,
    conflicts: list,
    gaps: list,
    degraded: bool,
    evidence: list | None = None,
    detail: str = DETAIL_DEFAULT,
    plan_echo: dict | None = None,
) -> dict:
    body = {
        "answer": answer,
        "detail": detail,
        "claims": claims,
        "conflicts": conflicts,
        "gaps": gaps,
        "degraded": bool(degraded),
        # The layer under claims: cited passages. Most of a corpus never becomes a claim,
        # and dropping these is how an answerable question looked unanswerable.
        "evidence": evidence or [],
    }
    if detail == "low":
        # `low` is the MCP default: the answer, the claims and why not, nothing else.
        body.pop("evidence")
    if detail == "high":
        # How the question was read, so a surprising answer can be audited in place.
        body["plan"] = plan_echo or {}
    return body


def _iso(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_prose(text: str) -> bool:
    """Reject structural noise (`}`, `"key": value,`) that a keyword search calls a hit.

    Corpus-agnostic on purpose: it measures the shape of the text, not a list of file names
    that this corpus happens to have.
    """
    stripped = text.strip()
    if len(stripped) < EVIDENCE_MIN_CHARS:
        return False
    alphanumeric = sum(char.isalnum() or char.isspace() for char in stripped)
    return alphanumeric / len(stripped) >= EVIDENCE_MIN_RATIO


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")


def _is_relevant(chunk: dict, question: str) -> bool:
    """Reject a passage that only coincidentally matched.

    Measured on this corpus, chunk cosine does not separate signal from noise: the top
    hits for "how does the console handle exceptions" and for "what cases are we covering"
    both score 0.75-0.79, because `nomic-embed-text` puts almost everything near 0.76. A
    threshold therefore cannot be the gate. Corroboration can:

    - a content word shared with the question is evidence, and
    - both channels agreeing (keyword *and* meaning) is evidence, and
    - meaning alone is **not** evidence, because that is exactly the "topically nearest
      text is usually the stale one" failure this product exists to avoid.
    """
    asked = {word.lower() for word in _WORD.findall(question)}
    text = str(chunk.get("text") or "").lower()
    if asked and any(word in text for word in asked):
        return True
    if asked:
        return "bm25" in str(chunk.get("via") or "") and "vector" in str(chunk.get("via") or "")
    return float(chunk.get("vector_score") or 0.0) >= EVIDENCE_MIN_COSINE


def _merge_claims(first: list[dict], second: list[dict]) -> list[dict]:
    """Union by statement+status, joining citations: one fact, every span that proves it."""
    out = {(row.get("statement"), row.get("status")): dict(row) for row in first}
    for row in second:
        key = (row.get("statement"), row.get("status"))
        if key in out:
            have = out[key].get("citations") or []
            for citation in row.get("citations") or []:
                if citation not in have:
                    have.append(citation)
            out[key]["citations"] = have
        else:
            out[key] = dict(row)
    return list(out.values())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
