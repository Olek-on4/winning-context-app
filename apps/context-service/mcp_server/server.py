# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""stdio MCP server: three workflow tools plus the citation reader, all over a ContextBackend.

The tools themselves live in `toolcall`, so the HTTP demo endpoint runs the same code.
MCP returns text, so each wrapper serialises the shared result.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

import toolcall
from models.protocols import ContextBackend


def _text(service: ContextBackend, name: str, params: dict[str, Any]) -> str:
    return toolcall.as_text(toolcall.call(service, name, params))


def context_search(
    service: ContextBackend,
    question: str,
    *,
    as_of: str | None = None,
    status_in: list[str] | None = None,
    token_budget: int = 2000,
) -> str:
    return _text(service, "context_search", {
        "question": question, "as_of": as_of, "status_in": status_in, "token_budget": token_budget,
    })


def context_explain_relationship(
    service: ContextBackend,
    question: str,
    *,
    as_of: str | None = None,
    status_in: list[str] | None = None,
    token_budget: int = 2000,
) -> str:
    return _text(service, "context_explain_relationship", {
        "question": question, "as_of": as_of, "status_in": status_in, "token_budget": token_budget,
    })


def context_risks(
    service: ContextBackend,
    question: str,
    *,
    as_of: str | None = None,
    status_in: list[str] | None = None,
    token_budget: int = 2000,
) -> str:
    return _text(service, "context_risks", {
        "question": question, "as_of": as_of, "status_in": status_in, "token_budget": token_budget,
    })


def resolve_span(service: ContextBackend, path: str, start: int, end: int) -> str:
    """The bytes a citation points at, or a JSON error instead of raising.

    Plain text on success (the agent reads it), a JSON object on failure.
    """
    result = toolcall.call(service, "resolve_span", {"path": path, "start": start, "end": end})
    return result["text"] if "text" in result else toolcall.as_text(result)


def build_server(service: ContextBackend) -> MCPServer:
    """Bind the tools to one backend instance; the caller owns its lifetime."""
    server = MCPServer(name="etyt-context", version="1.0")

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
        """How do A and B connect? Claims linking them, one hop, with evidence and dates."""
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
        """What is unsafe here? Claims of a violation or prohibition, with status and citations."""
        return context_risks(service, question, as_of=as_of, status_in=status_in, token_budget=token_budget)

    @server.tool(name="resolve_span")
    def resolve_span_tool(path: str, start: int, end: int) -> str:
        """Read the corpus bytes behind a citation (verify evidence before acting)."""
        return resolve_span(service, path, start, end)

    return server


def serve(service: ContextBackend) -> None:
    """Blocking stdio entry point for `ncs-mcp`."""
    build_server(service).run(transport="stdio")
