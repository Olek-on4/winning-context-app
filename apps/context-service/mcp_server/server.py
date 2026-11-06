"""stdio MCP server: three workflow tools plus the citation reader, all over ContextService.

Same service object as REST, so tool behaviour is testable without an MCP client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from api.spans import read_span

INTENT_BY_TOOL = {
    "context_search": "STATE_OF",
    "context_explain_relationship": "RELATIONSHIP",
    "context_risks": "RISKS",
}


def _answer_json(
    service: Any,
    question: str,
    intent: str,
    *,
    as_of: str | None,
    status_in: list[str] | None,
    token_budget: int,
) -> str:
    envelope = service.answer(
        question, intent=intent, as_of=as_of, status_in=status_in, token_budget=token_budget
    )
    # Sorted keys keep the wire form identical across runs and across tools.
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"))


def context_search(
    service: Any,
    question: str,
    *,
    as_of: str | None = None,
    status_in: list[str] | None = None,
    token_budget: int = 2000,
) -> str:
    return _answer_json(service, question, "STATE_OF", as_of=as_of, status_in=status_in, token_budget=token_budget)


def context_explain_relationship(
    service: Any,
    question: str,
    *,
    as_of: str | None = None,
    status_in: list[str] | None = None,
    token_budget: int = 2000,
) -> str:
    return _answer_json(service, question, "RELATIONSHIP", as_of=as_of, status_in=status_in, token_budget=token_budget)


def context_risks(
    service: Any,
    question: str,
    *,
    as_of: str | None = None,
    status_in: list[str] | None = None,
    token_budget: int = 2000,
) -> str:
    return _answer_json(service, question, "RISKS", as_of=as_of, status_in=status_in, token_budget=token_budget)


def resolve_span(service: Any, path: str, start: int, end: int) -> str:
    """Return the bytes a citation points at, or a JSON error instead of raising."""
    try:
        content = read_span(Path(service.corpus_root).resolve(), path, start, end)
    except FileNotFoundError:
        return json.dumps({"error": "not_found", "path": path}, sort_keys=True)
    except PermissionError:
        return json.dumps({"error": "path_escapes_corpus", "path": path}, sort_keys=True)
    except ValueError as exc:
        return json.dumps({"error": "bad_range", "detail": str(exc)}, sort_keys=True)
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return json.dumps({"error": "not_utf8", "path": path}, sort_keys=True)


def build_server(service: Any) -> MCPServer:
    """Bind the tools to one service instance; the caller owns the driver."""
    server = MCPServer(name="northstar-context", version="1.0")

    @server.tool(name="context_search")
    def context_search_tool(
        question: str,
        as_of: str | None = None,
        status_in: list[str] | None = None,
        token_budget: int = 2000,
    ) -> str:
        """What do we know about X? Ranked, status-labelled claims with citations."""
        return context_search(service, question, as_of=as_of, status_in=status_in, token_budget=token_budget)

    @server.tool(name="context_explain_relationship")
    def context_explain_relationship_tool(
        question: str,
        as_of: str | None = None,
        status_in: list[str] | None = None,
        token_budget: int = 2000,
    ) -> str:
        """How do A and B connect? Paths with per-hop evidence and dates."""
        return context_explain_relationship(
            service, question, as_of=as_of, status_in=status_in, token_budget=token_budget
        )

    @server.tool(name="context_risks")
    def context_risks_tool(
        question: str,
        as_of: str | None = None,
        status_in: list[str] | None = None,
        token_budget: int = 2000,
    ) -> str:
        """What is unsafe here? Risks with corroboration status and the safe pattern."""
        return context_risks(service, question, as_of=as_of, status_in=status_in, token_budget=token_budget)

    @server.tool(name="resolve_span")
    def resolve_span_tool(path: str, start: int, end: int) -> str:
        """Read the corpus bytes behind a citation (verify evidence before acting)."""
        return resolve_span(service, path, start, end)

    return server


def serve(service: Any) -> None:
    """Blocking stdio entry point for `ncs-mcp`."""
    build_server(service).run(transport="stdio")
