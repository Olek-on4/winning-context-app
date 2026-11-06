"""Transports are adapters: the envelope passes through unchanged, spans stay inside the corpus.

No Neo4j and no model run here; the service is a stub that records its calls.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from mcp_server.server import (
    build_server,
    context_explain_relationship,
    context_risks,
    context_search,
    resolve_span,
)
from sources import SpanStore, discover

CORPUS = Path(__file__).resolve().parents[3] / "vendor" / "att-hackathon-task"

# The frozen answer envelope, one claim, as a citation-only consumer sees it.
ENVELOPE = {
    "answer": "No. The Redis read cache was removed from the stock path on 2026-06-04.",
    "claims": [
        {
            "statement": "inventory-service reads availability directly from SQLite",
            "status": "VALID",
            "valid_from": "2026-06-04",
            "valid_to": None,
            "confidence": 0.96,
            "superseded_by": None,
            "citations": [
                {"path": "docs/adr/003-stock-cache.md", "lines": [6, 6], "hash": "9e1c0f"}
            ],
        }
    ],
    "conflicts": [],
    "gaps": ["No test covers the post-removal availability path."],
    "degraded": False,
}

CQP = {
    "cqp_version": "1.0",
    "intent": "STATE_OF",
    "anchors": [{"kind": "Service", "key": "inventory-service", "match": "exact"}],
    "traverse": {"predicates": ["READS_FROM"], "direction": "BOTH", "max_hops": 1, "max_nodes": 10},
    "time": {"as_of": "now", "status_in": ["VALID", "DEPRECATED"], "include_superseded_chain": True},
    "evidence": {"min_confidence": 0.5, "require_citations": True, "max_spans_per_claim": 2},
    "output": {"token_budget": 2000, "include_conflicts": True},
}


class StubService:
    spans = SpanStore(discover([CORPUS]))

    def __init__(self) -> None:
        self.answers: list[dict] = []
        self.plans: list[str] = []

    def answer(self, question, *, intent=None, as_of=None, status_in=None, token_budget=2000):
        self.answers.append(
            {
                "question": question,
                "intent": intent,
                "as_of": as_of,
                "status_in": status_in,
                "token_budget": token_budget,
            }
        )
        return ENVELOPE

    def plan(self, question):
        self.plans.append(question)
        return CQP


def client() -> TestClient:
    return TestClient(create_app(StubService()))


def test_query_passes_the_envelope_exactly() -> None:
    service = StubService()
    response = TestClient(create_app(service)).post(
        "/v1/query",
        json={
            "question": "does inventory use redis?",
            "as_of": "2026-01-01",
            "status_in": ["VALID"],
            "token_budget": 500,
        },
    )

    assert response.status_code == 200
    assert response.json() == ENVELOPE
    assert service.answers == [
        {
            "question": "does inventory use redis?",
            "intent": None,
            "as_of": "2026-01-01",
            "status_in": ["VALID"],
            "token_budget": 500,
        }
    ]


def test_query_defaults_are_the_contract_defaults() -> None:
    service = StubService()
    TestClient(create_app(service)).post("/v1/query", json={"question": "q"})

    assert service.answers[0]["as_of"] is None
    assert service.answers[0]["status_in"] is None
    assert service.answers[0]["token_budget"] == 2000


def test_plan_is_returned_without_execution() -> None:
    service = StubService()
    response = TestClient(create_app(service)).post("/v1/plan", json={"question": "does inventory use redis?"})

    assert response.json() == CQP
    assert service.plans == ["does inventory use redis?"]
    assert service.answers == []


def test_healthz() -> None:
    response = client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_span_returns_the_cited_bytes() -> None:
    response = client().get(
        "/v1/span", params={"path": "wiki/inventory-service.md", "start": 5, "end": 5}
    )

    expected = b"".join((CORPUS / "wiki" / "inventory-service.md").read_bytes().splitlines(keepends=True)[4:5])
    assert response.status_code == 200
    assert response.content == expected
    assert b"Redis read cache" in response.content


@pytest.mark.parametrize("path", ["../../AGENTS.md", "/etc/passwd", "wiki"])
def test_span_rejects_paths_outside_the_corpus(path: str) -> None:
    response = client().get("/v1/span", params={"path": path, "start": 1, "end": 1})

    assert response.status_code == 400


@pytest.mark.parametrize("path", ["wiki/does-not-exist.md"])
def test_span_missing_file_is_404(path: str) -> None:
    response = client().get("/v1/span", params={"path": path, "start": 1, "end": 1})

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("start", "end"), [(0, 1), (5, 4), (10, 10)]
)
def test_span_bad_range_is_400(start: int, end: int) -> None:
    response = client().get(
        "/v1/span", params={"path": "wiki/inventory-service.md", "start": start, "end": end}
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("handler", "intent"),
    [
        (context_search, "STATE_OF"),
        (context_explain_relationship, "RELATIONSHIP"),
        (context_risks, "RISKS"),
    ],
)
def test_tool_handlers_map_to_their_intent(handler, intent: str) -> None:
    service = StubService()

    payload = handler(service, "how do they connect?")

    assert service.answers[0]["intent"] == intent
    assert service.answers[0]["question"] == "how do they connect?"
    assert json.loads(payload) == ENVELOPE
    assert payload == handler(service, "how do they connect?")


def test_server_exposes_the_three_workflow_tools_and_the_span_reader() -> None:
    service = StubService()
    server = build_server(service)

    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {"context_search", "context_explain_relationship", "context_risks", "resolve_span"}

    result = asyncio.run(server.call_tool("context_search", {"question": "does inventory use redis?"}))
    assert service.answers[0]["intent"] == "STATE_OF"
    assert result.content[0].text == json.dumps(ENVELOPE, sort_keys=True, separators=(",", ":"))
    assert json.loads(result.content[0].text) == ENVELOPE


def test_resolve_span_helper_reads_the_pointer() -> None:
    service = StubService()

    text = resolve_span(service, "docs/adr/003-stock-cache.md", 6, 6)

    assert "Remove Redis from the local inventory path" in text
    assert json.loads(resolve_span(service, "../../AGENTS.md", 1, 1))["error"] == "path_escapes_corpus"
    assert json.loads(resolve_span(service, "missing.md", 1, 1))["error"] == "not_found"
    assert json.loads(resolve_span(service, "wiki/inventory-service.md", 5, 4))["error"] == "bad_range"


def test_one_server_serves_the_web_ui_and_the_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>ui</title>", encoding="utf-8")
    web = TestClient(create_app(StubService(), web_dist=tmp_path))

    page = web.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert web.get("/healthz").json() == {"status": "ok"}
    assert web.post("/v1/query", json={"question": "q"}).json() == ENVELOPE


def test_mcp_http_endpoint_lists_the_tools_the_stdio_server_registers() -> None:
    names = [tool["name"] for tool in client().get("/v1/mcp").json()]
    assert names == ["context_search", "context_explain_relationship", "context_risks", "resolve_span"]
    assert client().get("/v1/mcp").json()[0]["params"]["question"]["required"] is True


def test_mcp_http_call_returns_exactly_what_rest_returns() -> None:
    rest = client().post("/v1/query", json={"question": "q"}).json()
    body = client().post("/v1/mcp/context_search", json={"params": {"question": "q"}}).json()

    assert body["tool"] == "context_search"
    assert body["params"] == {"question": "q"}
    assert body["result"] == rest  # one implementation behind both transports


def test_mcp_http_rejects_an_unknown_tool_and_a_missing_parameter() -> None:
    assert client().post("/v1/mcp/nope", json={"params": {}}).status_code == 404
    assert client().post("/v1/mcp/context_risks", json={"params": {}}).status_code == 400


def test_mcp_http_span_returns_the_source_bytes() -> None:
    body = client().post(
        "/v1/mcp/resolve_span",
        json={"params": {"path": "docs/adr/003-stock-cache.md", "start": 6, "end": 6}},
    ).json()

    assert body["result"]["text"].strip()  # read from the corpus, not from the answer
    assert client().post("/v1/mcp/resolve_span", json={"params": {"path": "nope.md", "start": 1, "end": 2}}).json()["result"]["error"] == "not_found"
