"""Any object matching ContextBackend drives both transports: this test is the plug-in proof.

The backend below is not ContextService and imports nothing from retrieval — it just answers,
plans and serves span bytes out of memory.
"""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from api.app import create_app
from mcp_server.server import build_server, resolve_span

ENVELOPE = {"answer": "Adapters hold no rules.", "claims": [], "conflicts": [], "gaps": [], "degraded": False}


class MemorySpans:
    """Stand-in for SpanStore: proves the transports never touch the filesystem themselves."""

    def __init__(self) -> None:
        self.reads: list[tuple[str, int, int]] = []

    def read(self, pointer: str, start: int, end: int) -> bytes:
        self.reads.append((pointer, start, end))
        if pointer == "missing":
            raise FileNotFoundError(pointer)
        if pointer == "escape":
            raise PermissionError(pointer)
        return b"alpha\nbeta\n"


class StubBackend:
    def __init__(self) -> None:
        self.spans = MemorySpans()
        self.calls: list[dict] = []

    def answer(self, question, *, intent=None, as_of=None, status_in=None, token_budget=2000, effort=None, detail=None):
        self.calls.append(
            {"question": question, "intent": intent, "as_of": as_of, "status_in": status_in,
             "token_budget": token_budget}
        )
        return ENVELOPE

    def plan(self, question, *, intent=None):
        return {"intent": intent or "STATE_OF", "question": question}

    def explain(self, question, *, intent=None):
        return {**self.plan(question, intent=intent), "source": "deterministic"}


def client(service) -> TestClient:
    return TestClient(create_app(service))


def test_rest_and_mcp_return_the_same_envelope() -> None:
    service = StubBackend()

    rest = client(service).post("/v1/query", json={"question": "what holds?"})
    tool = asyncio.run(build_server(service).call_tool("context_search", {"question": "what holds?"}))

    assert rest.status_code == 200
    assert rest.json() == ENVELOPE == json.loads(tool.content[0].text)
    assert [call["intent"] for call in service.calls] == [None, "STATE_OF"]


def test_plan_passes_through_both_transports() -> None:
    service = StubBackend()

    rest = client(service).post("/v1/plan", json={"question": "what holds?"})

    assert rest.json() == {"intent": "STATE_OF", "question": "what holds?", "source": "deterministic"}


def test_span_route_reads_through_the_backend_only() -> None:
    service = StubBackend()

    response = client(service).get("/v1/span", params={"path": "not/a/real/file.md", "start": 1, "end": 2})

    assert response.status_code == 200
    assert response.content == b"alpha\nbeta\n"
    assert service.spans.reads == [("not/a/real/file.md", 1, 2)]


def test_span_errors_keep_their_http_semantics() -> None:
    service = StubBackend()

    assert client(service).get("/v1/span", params={"path": "missing", "start": 1, "end": 1}).status_code == 404
    assert client(service).get("/v1/span", params={"path": "escape", "start": 1, "end": 1}).status_code == 400


def test_mcp_span_tool_reads_through_the_backend_too() -> None:
    service = StubBackend()

    assert resolve_span(service, "not/a/real/file.md", 1, 2) == "alpha\nbeta\n"
    assert json.loads(resolve_span(service, "missing", 1, 1))["error"] == "not_found"
    assert json.loads(resolve_span(service, "escape", 1, 1))["error"] == "path_escapes_corpus"
    assert len(service.spans.reads) == 3
