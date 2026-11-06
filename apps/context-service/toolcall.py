# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The four MCP tools, callable without an MCP client.

Both transports import from here, so the stdio server and the HTTP demo endpoint run
the same function over the same ContextBackend. There is no second implementation to
drift.
"""

from __future__ import annotations

import json
from typing import Any

from models.protocols import ContextBackend

QUESTION_ANSWER = "answer"

# What each endpoint accepts. The UI renders this list, so the demo shows real
# parameters instead of a hand-written caption that can go stale.
TOOL_SPECS: dict[str, dict[str, Any]] = {
    "context_search": {
        "intent": "STATE_OF",
        "summary": "What is true about a component now (or as of a date), with status and citations.",
        "params": {
            "question": {"type": "string", "required": True},
            "as_of": {"type": "string", "format": "date", "required": False},
            "status_in": {"type": "array", "items": "string", "required": False},
            "token_budget": {"type": "integer", "default": 2000},
        },
    },
    "context_explain_relationship": {
        "intent": "RELATIONSHIP",
        "summary": "How two things are related, or why they are not.",
        "params": {
            "question": {"type": "string", "required": True},
            "as_of": {"type": "string", "format": "date", "required": False},
            "status_in": {"type": "array", "items": "string", "required": False},
            "token_budget": {"type": "integer", "default": 2000},
        },
    },
    "context_risks": {
        "intent": "RISKS",
        "summary": "What is stale, disputed or contradictory around a subject.",
        "params": {
            "question": {"type": "string", "required": True},
            "as_of": {"type": "string", "format": "date", "required": False},
            "status_in": {"type": "array", "items": "string", "required": False},
            "token_budget": {"type": "integer", "default": 2000},
        },
    },
    "resolve_span": {
        "intent": "EVIDENCE",
        "summary": "The exact source lines a citation points at. The anti-hallucination check.",
        "params": {
            "path": {"type": "string", "required": True},
            "start": {"type": "integer", "required": True},
            "end": {"type": "integer", "required": True},
        },
    },
}


def _answer(
    service: ContextBackend,
    question: str,
    intent: str,
    *,
    as_of: str | None,
    status_in: list[str] | None,
    token_budget: int,
) -> dict[str, Any]:
    return service.answer(
        question, intent=intent, as_of=as_of, status_in=status_in, token_budget=token_budget
    )


def span(service: ContextBackend, path: str, start: int, end: int) -> dict[str, Any]:
    """The cited bytes, or an error object — never an exception reaching the transport."""
    try:
        content = service.spans.read(path, start, end)
    except FileNotFoundError:
        return {"error": "not_found", "path": path}
    except PermissionError:
        return {"error": "path_escapes_corpus", "path": path}
    except ValueError as exc:
        return {"error": "bad_range", "detail": str(exc), "path": path}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {"error": "not_utf8", "path": path}
    return {"path": path, "start": start, "end": end, "text": text}


def call(service: ContextBackend, name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Run one tool by name. Unknown name or missing parameter is a caller error."""
    spec = TOOL_SPECS.get(name)
    if spec is None:
        raise KeyError(name)
    for key, schema in spec["params"].items():
        if schema.get("required") and params.get(key) in (None, ""):
            raise ValueError(f"{name} requires {key}")
    question = str(params.get("question") or "")
    if name == "resolve_span":
        return span(service, str(params["path"]), int(params["start"]), int(params["end"]))
    envelope = _answer(
        service,
        question,
        str(spec["intent"]),
        as_of=(params.get("as_of") or None),
        status_in=params.get("status_in") or None,
        token_budget=int(params.get("token_budget") or 2000),
    )
    return envelope


def as_text(result: dict[str, Any]) -> str:
    """Sorted keys keep the wire form identical across runs and across transports."""
    return json.dumps(result, sort_keys=True, separators=(",", ":"))
