"""The one service layer: plan -> validate -> compile -> execute -> assemble.

Assembled claims are pointers (path, lines, hash), never prose. The text is verified
against the corpus at read time, so a stale graph cannot produce a false citation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from graph.resolver import Status
from retrieval import hybrid, planner
from retrieval.cqp import MAX_NODES, MAX_SPANS, CQP, compile as compile_cqp, validate_plan

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


class ContextService:
    def __init__(self, driver, corpus_root: Path):
        self.driver = driver
        self.corpus_root = Path(corpus_root)
        self._documents: dict[str, tuple[list[str], str] | None] = {}

    def plan(self, question: str, *, intent: str | None = None) -> dict:
        """The query plan, inspectable and unexecuted: /v1/plan's whole contract."""
        return planner.plan(question, intent=intent).model_dump()

    def answer(
        self,
        question: str,
        *,
        intent: str | None = None,
        as_of: str | None = None,
        status_in: list[str] | None = None,
        token_budget: int = 2000,
    ) -> dict:
        gaps: list[str] = []
        degraded = False

        try:
            base = CQP.model_validate(self.plan(question, intent=intent))
        except Exception as exc:
            return _envelope(
                "No answer: the planner is unavailable.",
                [],
                [],
                [f"Planner failed ({type(exc).__name__})."],
                True,
            )

        try:
            plan = validate_plan(_overridden(base, as_of, status_in, token_budget).model_dump())
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
            )

        try:
            rows = _execute(self.driver, cypher, params)
        except Exception as exc:
            rows = []
            degraded = True
            gaps.append(f"Graph query failed ({type(exc).__name__}).")
            chunks, _ = _hybrid(self.driver, question)
            if chunks:
                top = chunks[0]
                where = (
                    f"{top['path']}:{top['lines'][0]}"
                    if top["path"] and top["lines"]
                    else top["path"] or "unknown"
                )
                gaps.append(f"Hybrid search matched {len(chunks)} chunks (top {where}).")
            else:
                gaps.append("Hybrid search also returned nothing.")

        claims, conflicts, assemble_gaps = self._assemble(rows, plan)
        gaps.extend(assemble_gaps)
        if not rows and not degraded:
            gaps.append("No claims matched the plan.")

        answer = _answer_text(claims)
        claims, conflicts, truncated = _spend_budget(
            claims, conflicts, answer, plan.output.token_budget
        )
        if truncated:
            gaps.insert(0, f"Response truncated to {plan.output.token_budget} tokens.")

        return _envelope(answer, claims, conflicts, _dedupe(gaps), degraded)

    def _assemble(self, rows: list[dict], plan: CQP) -> tuple[list[dict], list[dict], list[str]]:
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
            citations, citation_gaps = self._verify(list(row.get("citations") or []), max_spans)
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
                    "id": key,
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
                }
                continue

            entry["confidence"] = max(entry["confidence"], round(confidence, 4))
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

        _link_superseded(claims)
        conflicts = _conflicts(claims) if plan.output.include_conflicts else []

        projected = [{field: claim[field] for field in _CLAIM_FIELDS} for claim in claims]
        return projected, conflicts, gaps

    def _verify(self, citations: list, max_spans: int) -> tuple[list[dict], list[str]]:
        out: list[dict] = []
        gaps: list[str] = []
        seen: set[tuple] = set()

        for item in citations[:max_spans]:
            if not isinstance(item, dict):
                gaps.append("Citation was not a mapping.")
                continue
            path = str(item.get("path") or "")
            start, end = item.get("start_line"), item.get("end_line")
            if not path or start is None or end is None:
                gaps.append("Citation is missing a path or line range.")
                continue
            try:
                start, end = int(start), int(end)
            except (TypeError, ValueError):
                gaps.append(f"Citation {path} has non-numeric lines.")
                continue

            document = self._document(path)
            if document is None:
                gaps.append(f"Citation {path} is outside the corpus root.")
                continue
            lines, digest = document
            if not 1 <= start <= end <= len(lines):
                gaps.append(f"Citation {path}:{start}-{end} is outside the file.")
                continue
            stored = str(item.get("hash") or "").strip()
            if stored and not (digest.startswith(stored) or stored.startswith(digest)):
                gaps.append(f"Citation {path}:{start}-{end} failed hash verification.")
                continue
            key = (path, start, end)
            if key in seen:
                continue
            seen.add(key)
            out.append({"path": path, "lines": [start, end], "hash": stored or digest})

        return out, gaps

    def _document(self, path: str) -> tuple[list[str], str] | None:
        if path in self._documents:
            return self._documents[path]
        document: tuple[list[str], str] | None = None
        try:
            root = self.corpus_root.resolve()
            target = (root / path).resolve()
            if target.is_relative_to(root) and target.is_file():
                raw = target.read_bytes()
                text = raw.decode("utf-8", errors="replace")
                document = (text.splitlines(), hashlib.sha256(raw).hexdigest())
        except OSError:
            document = None
        self._documents[path] = document
        return document


def _execute(driver, cypher: str, params: dict) -> list[dict]:
    with driver.session() as session:
        result = session.run(cypher, **params)
        return [dict(record) for record in result]


def _hybrid(driver, question: str) -> tuple[list[dict], bool]:
    # The graph call failed, so the same driver may be unavailable too; degrade quietly.
    try:
        return hybrid.search(driver, question)
    except Exception:
        return [], True


def _overridden(base: CQP, as_of, status_in, token_budget) -> CQP:
    updates: dict = {}
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


def _link_superseded(claims: list[dict]) -> None:
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
        claim["superseded_by"] = (
            winner["citations"][0]["path"] if winner["citations"] else winner["id"]
        )


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


def _answer_text(claims: list[dict]) -> str:
    valid = [claim for claim in claims if claim["status"] == Status.VALID.value]
    deprecated = [claim for claim in claims if claim["status"] == Status.DEPRECATED.value]
    parts: list[str] = []
    if valid:
        parts.append("; ".join(claim["statement"] for claim in valid[:3]))
    if deprecated:
        parts.append("Superseded: " + "; ".join(claim["statement"] for claim in deprecated[:2]))
    if not parts:
        return "No validated claims matched the question."
    text = ". ".join(parts)
    return text[:1].upper() + text[1:] + "."


def _spend_budget(
    claims: list[dict], conflicts: list[dict], answer: str, budget: int
) -> tuple[list[dict], list[dict], bool]:
    """Spend in documented order: answer, one citation per claim, conflicts, extras."""
    remaining = max(int(budget), 1) - _tokens(answer)
    truncated = False
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

    for original, kept in paired:
        for citation in original["citations"][1:]:
            cost = _tokens(citation["path"]) + 4
            if cost > remaining:
                truncated = True
                break
            remaining -= cost
            kept["citations"].append(citation)

    return [kept for _, kept in paired], kept_conflicts, truncated


def _claim_cost(claim: dict, citation_count: int) -> int:
    cost = _tokens(claim["statement"]) + 6
    for citation in claim["citations"][:citation_count]:
        cost += _tokens(citation["path"]) + 4
    return cost


def _tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _envelope(answer: str, claims: list, conflicts: list, gaps: list, degraded: bool) -> dict:
    return {
        "answer": answer,
        "claims": claims,
        "conflicts": conflicts,
        "gaps": gaps,
        "degraded": bool(degraded),
    }


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


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
