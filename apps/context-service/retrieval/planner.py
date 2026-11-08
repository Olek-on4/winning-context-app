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

from logging_setup import logger
from retrieval.cqp import CQP, Anchor, Intent, TimeFilter, Traverse, validate_plan
from settings import AUTO_EFFORT, AUTO_EFFORT_NAMED, MODEL_KEEP_ALIVE, MODEL_TIMEOUT_S, PREDICATE_CUES
from settings import OLLAMA_HOST as DEFAULT_HOST
from settings import PLANNER_MODEL as DEFAULT_MODEL

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
_IDENTIFIERS = (
    re.compile(r"`([^`\n]{1,80})`"),
    re.compile(r"\"([^\"\n]{1,80})\""),
    re.compile(r"'([^'\n]{1,80})'"),
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"),
    re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b"),
    re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b"),
    re.compile(r"\b\d{4,5}\b"),
    re.compile(r"/[A-Za-z0-9][A-Za-z0-9._/-]{1,80}"),  # REST paths: /v1/accounts
)


def plan(
    question: str,
    intent: str | None = None,
    model: bool = True,
    trace: dict[str, str] | None = None,
) -> CQP:
    """Never raises. Deterministic first (ADR-0005): the keyword plan covers every
    question that names an identifier, service, table or endpoint. The model is the
    fallback for questions that name nothing, and never overrides a deterministic plan.

    `model=False` disables even that fallback. `trace`, when given, is filled with where
    the plan came from so the caller can show it: "the model never ran" and "the model ran
    and agreed" are different answers to "is this parsed or understood".
    """
    result: CQP | None = None
    try:
        result = _keywords(question, intent)
    except Exception:
        result = None
    # A question without a quoted, dotted, dashed or CamelCase identifier names nothing
    # the keyword planner can type, so it gets one model attempt. With an identifier the
    # deterministic plan wins and the model is never called (ADR-0005).
    if trace is not None:
        trace["source"] = "deterministic"
    if model and _names_an_identifier(question):
        if trace is not None:
            trace["detail"] = "the question names an identifier; ADR-0005 keeps the keyword plan"
    elif model:
        try:
            modelled = _from_model(question)
        except Exception as exc:
            _warn_model(exc)
            modelled = None
            if trace is not None:
                trace["detail"] = f"model call failed: {type(exc).__name__}"
        # The model refines, it never replaces: only a typed anchor (a Service, Table or
        # Endpoint it recognised) beats the keyword plan. An all-ANY model plan lost
        # evidence on the accounts and payments questions, so it is discarded.
        if modelled is not None and any(a.kind != "ANY" for a in modelled.anchors):
            result = modelled
            if trace is not None:
                trace["source"] = "model"
                trace["detail"] = "typing anchors only the model resolved"
        elif trace is not None:
            trace.setdefault("detail", "model plan carried no typed anchor; discarded")
    if result is None:
        return _safe(question)
    # Semi-automatic effort: a named thing is already an exact match, a question that
    # names nothing is the case meaning search exists for. The caller may override it.
    if trace is not None:
        trace.setdefault("effort", str(AUTO_EFFORT))
    result = result.model_copy(
        update={"effort": AUTO_EFFORT_NAMED if _names_an_identifier(question) else AUTO_EFFORT}
    )
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
    timeout = float(os.environ.get("OLLAMA_TIMEOUT", MODEL_TIMEOUT_S))
    keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", MODEL_KEEP_ALIVE)
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
    return validate_plan(_repair(json.loads(_strip_fences(response.json()["response"]))))


def _repair(payload: dict) -> dict:
    """Model output is untrusted: fix the shape, never the meaning.

    An anchor carries `key` or `text`, never both and never neither; a small model fills
    both with the same word, which the schema rejects. `time.as_of` is a calendar date —
    models like to append a time and a zone. Nothing here invents a value.
    """
    time = payload.get("time")
    if isinstance(time, dict) and isinstance(time.get("as_of"), str):
        raw = time["as_of"].strip()
        payload = {**payload, "time": {**time, "as_of": raw[:10] if len(raw) >= 10 and raw[4] == "-" else None}}
    anchors = []
    for anchor in payload.get("anchors") or []:
        if not isinstance(anchor, dict):
            continue
        key = (anchor.get("key") or "").strip() or None
        text = (anchor.get("text") or "").strip() or None
        if key:
            anchors.append({**anchor, "key": key, "text": None})
        elif text:
            anchors.append({**anchor, "key": None, "text": text})
    return {**payload, "anchors": anchors}


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
        traverse=Traverse(predicates=predicates),
        time=_time_for(chosen, as_of),
    )


def _names_an_identifier(question: str) -> bool:
    """True when the question carries something the keyword planner can type exactly."""
    return any(pattern.search(question) for pattern in _IDENTIFIERS)


_LOG = logger("planner")
_MODEL_WARNED: set[str] = set()


def _warn_model(exc: Exception) -> None:
    """One line per distinct failure: a silent fallback looks like a healthy planner."""
    key = f"{type(exc).__name__}: {exc}"[:200]
    if key not in _MODEL_WARNED:
        _MODEL_WARNED.add(key)
        _LOG.warning("model unavailable, using the deterministic plan (%s)", key)


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


def _anchors(question: str) -> list[Anchor]:
    """Candidate anchors, unfiltered: the graph decides which of these are words at all.

    There is no stopword list here on purpose. A token is noise if no entity key contains
    it, and that is a property of the corpus, not of English (see `ContextService._attested`).
    """
    found: list[str] = []
    for pattern in _IDENTIFIERS:
        for match in pattern.finditer(question):
            token = (match.group(1) if match.lastindex else match.group(0)).strip()
            if token and len(token) <= 80 and token not in found:
                found.append(token)
    if not found:
        # Every word is a candidate; `_attested` keeps the ones the corpus knows. No
        # stopword list, so this works for a corpus in any language.
        found = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", question)[:8]
    anchors: list[Anchor] = []
    for token in found[:8]:
        if " " in token:
            anchors.append(Anchor(kind="ANY", text=token, match="hybrid"))
        else:
            anchors.append(Anchor(kind="ANY", key=token, match="exact"))
    return anchors


def _predicates(question: str) -> list[str]:
    """Predicates named in the question, from the ontology's own vocabulary.

    Two sources, both declared rather than guessed: a predicate written literally in the
    question, and the cue words `settings.PREDICATE_CUES` maps onto it.
    """
    lower = question.lower()
    found = {name for name in _PREDICATE_NAMES if re.search(rf"\b{name.lower()}\b", lower)}
    for predicate, cues in PREDICATE_CUES.items():
        if any(re.search(rf"\b{re.escape(cue)}\b", lower) for cue in cues):
            found.add(predicate)
    return sorted(found)
