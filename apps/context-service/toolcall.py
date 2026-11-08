# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The four MCP tools, callable without an MCP client.

Both transports import from here, so the stdio server and the HTTP demo endpoint run
the same function over the same ContextBackend. There is no second implementation to
drift.

# shortcut: demo-only dual transport. `models/` is the only module every workstream is
# meant to import (AGENTS.md Layout); merge this into `models/tools.py`, or give each
# adapter its own, once the demo is over and the owners agree.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from models.protocols import ContextBackend
from settings import DETAIL_DEFAULT_MCP, DETAIL_LEVELS, EFFORT_MAX, TOKEN_BUDGET

QUESTION_ANSWER = "answer"

_INTEGER = re.compile(r"[+-]?\d+")

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
            "token_budget": {"type": "integer", "default": TOKEN_BUDGET},
            "effort": {"type": "integer", "minimum": 0, "maximum": EFFORT_MAX, "required": False},
            "detail": {
                "type": "string",
                "enum": list(DETAIL_LEVELS),
                "default": DETAIL_DEFAULT_MCP,
                "required": False,
            },
        },
    },
    "context_explain_relationship": {
        "intent": "RELATIONSHIP",
        "summary": "How two things are related, or why they are not.",
        "params": {
            "question": {"type": "string", "required": True},
            "as_of": {"type": "string", "format": "date", "required": False},
            "status_in": {"type": "array", "items": "string", "required": False},
            "token_budget": {"type": "integer", "default": TOKEN_BUDGET},
            "effort": {"type": "integer", "minimum": 0, "maximum": EFFORT_MAX, "required": False},
            "detail": {
                "type": "string",
                "enum": list(DETAIL_LEVELS),
                "default": DETAIL_DEFAULT_MCP,
                "required": False,
            },
        },
    },
    "context_risks": {
        "intent": "RISKS",
        "summary": "What is stale, disputed or contradictory around a subject.",
        "params": {
            "question": {"type": "string", "required": True},
            "as_of": {"type": "string", "format": "date", "required": False},
            "status_in": {"type": "array", "items": "string", "required": False},
            "token_budget": {"type": "integer", "default": TOKEN_BUDGET},
            "effort": {"type": "integer", "minimum": 0, "maximum": EFFORT_MAX, "required": False},
            "detail": {
                "type": "string",
                "enum": list(DETAIL_LEVELS),
                "default": DETAIL_DEFAULT_MCP,
                "required": False,
            },
        },
    },
    "resolve_span": {
        "intent": "EVIDENCE",
        "summary": "The exact source lines a citation points at. The anti-hallucination check.",
        "params": {
            "path": {"type": "string", "required": True},
            "start": {"type": "integer", "required": False},
            "end": {"type": "integer", "required": False},
            "region": {"type": "string", "required": False},
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
    effort: int | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    return service.answer(
        question,
        intent=intent,
        as_of=as_of,
        status_in=status_in,
        token_budget=token_budget,
        effort=effort,
        detail=detail or DETAIL_DEFAULT_MCP,
    )


def span(
    service: ContextBackend, path: str, start: int | None = None, end: int | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """The cited bytes, or an error object — never an exception reaching the transport.

    An image citation is a rectangle, `x,y,w,h`; it resolves to a PNG of that crop (or the
    whole file when no decoder is installed), never to a text decode of image bytes.
    """
    if region:
        try:
            x, y, w, h = (int(part) for part in region.split(","))
        except ValueError:
            return {"error": "bad_region", "detail": "region must be x,y,w,h", "path": path}
        try:
            content = service.spans.read_region(path, (x, y, w, h))
        except FileNotFoundError:
            return {"error": "not_found", "path": path}
        except PermissionError:
            return {"error": "path_escapes_corpus", "path": path}
        except ValueError as exc:
            return {"error": "bad_region", "detail": str(exc), "path": path}
        return {"path": path, "region": [x, y, w, h], "media_type": "image/png",
                "bytes": len(content), "image_base64": __import__("base64").b64encode(content).decode()}
    if start is None or end is None:
        # A caller error, not a corpus fact: the transports map ValueError to 400.
        raise ValueError("resolve_span needs start and end, or a region as x,y,w,h")
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


def _as_integer(name: str, key: str, value: Any) -> int:
    """Bools are ints in Python, and a list is not a number: both are caller errors."""
    if isinstance(value, bool):
        # ValueError, not TypeError: both transports map ValueError to a 400 (#71).
        raise ValueError(f"{name} parameter {key} must be an integer")  # noqa: TRY004
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
        return int(value)
    raise ValueError(f"{name} parameter {key} must be an integer")


def _as_date(name: str, key: str, value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} parameter {key} must be an ISO date (YYYY-MM-DD)") from None
    return value


def _checked(name: str, key: str, schema: dict[str, Any], value: Any) -> Any:
    kind = schema.get("type")
    if kind == "integer":
        return _as_integer(name, key, value)
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{name} parameter {key} must be a string")
        return _as_date(name, key, value) if schema.get("format") == "date" else value
    if kind == "array":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{name} parameter {key} must be an array of strings")
        return list(value)
    raise ValueError(f"{name} parameter {key} has unknown schema type {kind!r}")


def params_for(name: str, spec: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Coerce and type-check every declared parameter, once, against `TOOL_SPECS`.

    A mistyped `start` used to reach `int(params["start"])` and raise TypeError, which no
    transport caught, so a client error became a 500 (#71). Every failure here is a
    ValueError naming the parameter, which both transports already map to 400.
    """
    if not isinstance(params, dict):
        raise ValueError(f"{name} expects a parameter object")  # noqa: TRY004 — a 400, not a 500
    values: dict[str, Any] = {}
    for key, schema in spec["params"].items():
        value = params.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if schema.get("required"):
                raise ValueError(f"{name} requires {key}")
            if "default" in schema:
                values[key] = schema["default"]
            continue
        values[key] = _checked(name, key, schema, value)
    return values


def call(service: ContextBackend, name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Run one tool by name. Unknown name or bad parameter is a caller error, not a crash."""
    spec = TOOL_SPECS.get(name)
    if spec is None:
        raise KeyError(name)
    values = params_for(name, spec, params)
    if name == "resolve_span":
        return span(service, values["path"], values.get("start"), values.get("end"),
                    values.get("region"))
    envelope = _answer(
        service,
        values["question"],
        str(spec["intent"]),
        as_of=values.get("as_of") or None,
        status_in=values.get("status_in") or None,
        token_budget=int(values.get("token_budget") or TOKEN_BUDGET),
        effort=values.get("effort"),
        detail=values.get("detail"),
    )
    return envelope


def as_text(result: dict[str, Any]) -> str:
    """Sorted keys keep the wire form identical across runs and across transports."""
    return json.dumps(result, sort_keys=True, separators=(",", ":"))
