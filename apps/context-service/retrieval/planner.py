"""Question -> CQP. A local model fills slots; a deterministic planner is the floor.

The planner sees the user's question only (AGENTS invariant 3) and never raises:
any model failure degrades to keyword classification and regex identifiers.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date

import httpx

from retrieval.cqp import CQP, Anchor, Intent, TimeFilter, Traverse, validate_plan

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"

# All five states a claim can hold. The answer labels each one, so hiding PROPOSED or
# DISPUTED would only make the service look more certain than it is.
_HISTORY_STATUSES = ["VALID", "DEPRECATED", "PLANNED", "PROPOSED", "DISPUTED"]

_PREDICATE_NAMES = {
    "CALLS", "READS_FROM", "WRITES_TO", "EXPOSES", "LISTENS_ON", "AUTHENTICATES_VIA",
    "DEPENDS_ON", "IMPORTS", "BUILDS_FROM", "DEPLOYED_BY", "DEFINES_TABLE", "HAS_COLUMN",
    "MIGRATES", "SHARES_SCHEMA_WITH", "OWNS", "DECIDED_BY", "SUPERSEDES", "IMPLEMENTS",
    "VIOLATES", "PROHIBITS", "MENTIONS", "CAUSED_BY", "RESOLVED_BY", "PLANNED_IN",
    "DISCUSSED_IN",
}
_PREDICATE_PHRASES = {
    "depends on": "DEPENDS_ON",
    "reads from": "READS_FROM",
    "writes to": "WRITES_TO",
    "authenticates via": "AUTHENTICATES_VIA",
    "owns": "OWNS",
    "violates": "VIOLATES",
    "supersedes": "SUPERSEDES",
    "implemented by": "IMPLEMENTS",
    "prohibits": "PROHIBITS",
    "exposes": "EXPOSES",
    "expose": "EXPOSES",
}

_IDENTIFIERS = (
    re.compile(r"`([^`\n]{1,80})`"),
    re.compile(r"\"([^\"\n]{1,80})\""),
    re.compile(r"'([^'\n]{1,80})'"),
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"),
    re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b"),
    re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b"),
    re.compile(r"\b\d{4,5}\b"),
)


def plan(question: str, intent: str | None = None, model: bool = True) -> CQP:
    """Never raises. Deterministic first (ADR-0005): the keyword plan covers every
    question that names an identifier, service, table or endpoint. The model is the
    fallback for questions that name nothing, and never overrides a deterministic plan.

    `model=False` disables even that fallback.
    """
    result: CQP | None = None
    try:
        result = _keywords(question, intent)
    except Exception:
        result = None
    if model and (result is None or _unanchored(result)):
        try:
            modelled = _from_model(question)
        except Exception:
            modelled = None
        if modelled is not None:
            result = modelled
    if result is None:
        return _safe(question)
    if intent is not None:
        try:
            forced = Intent(str(intent).strip().upper())
            result = result.model_copy(
                update={"intent": forced, "time": _time_for(forced, result.time.as_of)}
            )
        except Exception:
            pass
    if result is not None and result.time.as_of and not _TEMPORAL_HINT.search(question):
        # The model invents a point in time for questions that carry none. Honouring it
        # silently filters every current claim out and reads as "no evidence".
        result = result.model_copy(
            update={"time": result.time.model_copy(update={"as_of": None})}
        )
    return result


def _from_model(question: str) -> CQP:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    timeout = float(os.environ.get("OLLAMA_TIMEOUT", "10"))
    keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
    payload = {
        "model": model,
        "prompt": _prompt(question),
        "stream": False,
        "format": CQP.model_json_schema(),
        # keep_alive keeps the 2.6 GB planner resident: a cold load on the 3060 takes
        # 34 s, which is longer than this timeout, so every cold query used to fall back.
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "num_predict": 256},
    }
    response = httpx.post(f"{host}/api/generate", json=payload, timeout=timeout)
    response.raise_for_status()
    return validate_plan(json.loads(_strip_fences(response.json()["response"])))


def _prompt(question: str) -> str:
    return (
        "You fill a Context Query Plan for a Neo4j claim graph. Return only JSON.\n"
        "intent is exactly one of: LOOKUP, STATE_OF, RELATIONSHIP, CONFLICTS, TIMELINE, RISKS.\n"
        "anchors name the entities in the question. Use key for exact identifiers and text "
        "for fuzzy phrases. traverse.predicates are uppercase relationship names. "
        "time.as_of is an ISO date or null. time.status_in defaults to [\"VALID\"]. "
        "output.token_budget is a positive integer.\n"
        "Question: " + question.strip()
    )


def _strip_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _safe(question: str) -> CQP:
    text = (question or "").strip()[:200] or "?"
    return CQP(intent=Intent.LOOKUP, anchors=[Anchor(kind="ANY", text=text, match="hybrid")])


def _keywords(question: str, intent: str | None = None) -> CQP:
    q = (question or "").strip()
    lower = q.lower()
    forced = _forced_intent(intent)
    chosen = forced or _detect_intent(lower)
    as_of = _as_of(q)

    anchors = _anchors(q)
    if not anchors:
        anchors = [Anchor(kind="ANY", text=q[:200] or "?", match="hybrid")]

    predicates = _predicates(q)
    if chosen is Intent.RISKS:
        predicates = sorted(set(predicates) | {"VIOLATES", "PROHIBITS"})

    return CQP(
        intent=chosen,
        anchors=anchors,
        traverse=Traverse(
            predicates=predicates,
            max_hops=2 if chosen is Intent.RELATIONSHIP else 1,
        ),
        time=_time_for(chosen, as_of),
    )


def _unanchored(cqp: CQP) -> bool:
    """True when the plan names nothing: only then is a model plan worth the round trip."""
    return not any(anchor.key for anchor in cqp.anchors)


def _forced_intent(intent: str | None) -> Intent | None:
    if intent is None:
        return None
    try:
        return Intent(str(intent).strip().upper())
    except ValueError:
        return None


def _detect_intent(lower: str) -> Intent:
    if re.search(r"\b(conflict|conflicts|disagree\w*|contradict\w*)\b", lower):
        return Intent.CONFLICTS
    if re.search(r"\b(risk|risks|unsafe|vulnerab\w*|security|cwe-?\d+)\b", lower):
        return Intent.RISKS
    if re.search(r"\b(timeline|history|historical|changed|change over)\b", lower):
        return Intent.TIMELINE
    if re.search(r"\b(connect|connection|relationship|related)\b", lower):
        return Intent.RELATIONSHIP
    if re.search(r"\bbetween\b.+\band\b", lower):
        return Intent.RELATIONSHIP
    if re.search(r"\bstill\b|\bstate of\b|\bdoes .+ (use|read|depend on)\b", lower):
        return Intent.STATE_OF
    return Intent.LOOKUP


def _time_for(intent: Intent, as_of: str | None) -> TimeFilter:
    statuses = {
        Intent.TIMELINE: _HISTORY_STATUSES,
        Intent.CONFLICTS: ["DISPUTED"],
        Intent.RISKS: ["VALID", "DISPUTED"],
    }.get(intent, _HISTORY_STATUSES)  # every known state; the row carries its label
    return TimeFilter(
        as_of=as_of,
        status_in=list(statuses),
        include_superseded_chain=intent in {Intent.STATE_OF, Intent.RELATIONSHIP},
    )


# A question only constrains time if it names one; otherwise a model-provided as_of is
# a guess that hides the present.
_TEMPORAL_HINT = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{4}|january|february|march|april|may|june|july|august"
    r"|september|october|november|december)\b",
    re.IGNORECASE,
)


def _as_of(question: str) -> str | None:
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", question)
    if match is None:
        return None
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        return None
    return match.group(1)


# Words that carry no anchor value; keeps plain-English questions findable.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "does", "do", "did", "still", "have",
    "has", "had", "what", "which", "who", "how", "where", "when", "why", "any",
    "and", "or", "of", "in", "on", "for", "to", "from", "with", "about", "use", "uses",
    "using", "table", "fields", "field", "columns", "system", "service", "there", "tell",
    "me", "we", "it", "current", "currently", "now", "status", "value", "happened",
    "happen", "changed", "change", "used", "make", "makes", "work", "works",
}


def _anchors(question: str) -> list[Anchor]:
    found: list[str] = []
    for pattern in _IDENTIFIERS:
        for match in pattern.finditer(question):
            token = (match.group(1) if match.lastindex else match.group(0)).strip()
            if token and len(token) <= 80 and token not in found:
                found.append(token)
    if not found:
        # No identifier in the question: content words still hit entity keys such as
        # `users` or `invoices`. Keep more than three — the entity is often mentioned
        # late ("what happened to state in invoices").
        found = [
            word.lower()
            for word in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", question)
            if word.lower() not in _STOPWORDS
        ][:6]
    anchors: list[Anchor] = []
    for token in found[:4]:
        if " " in token:
            anchors.append(Anchor(kind="ANY", text=token, match="hybrid"))
        else:
            anchors.append(Anchor(kind=_kind(token), key=token, match="exact"))
    return anchors


def _kind(token: str) -> str:
    if re.fullmatch(r"\d{4,5}", token):
        return "Port"
    if re.fullmatch(r"[A-Z][A-Z0-9_]+", token):
        return "EnvVar"
    if token.endswith(("-service", "-gateway")):
        return "Service"
    return "ANY"


def _predicates(question: str) -> list[str]:
    lower = question.lower()
    found = {name for name in _PREDICATE_NAMES if re.search(rf"\b{name}\b", question)}
    for phrase, name in _PREDICATE_PHRASES.items():
        if phrase in lower:
            found.add(name)
    return sorted(found)
