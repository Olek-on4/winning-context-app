"""FastAPI transport. Routes translate HTTP into ContextBackend calls; no rules live here."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import toolcall
from logging_setup import request_logger
from models.protocols import ContextBackend
from settings import OLLAMA_HOST, TOKEN_BUDGET


class QueryBody(BaseModel):
    question: str
    as_of: str | None = None
    status_in: list[str] | None = None
    token_budget: int = TOKEN_BUDGET
    # 0-4, semi-automatic: omit it and the planner decides; send it and it wins.
    effort: int | None = None
    # low | medium | high: how much of what was found comes back. REST keeps `medium`,
    # the envelope the UI renders; MCP defaults to `low` because an agent pays per token.
    detail: str | None = None


class PlanBody(BaseModel):
    question: str


class ExecuteBody(BaseModel):
    plan: dict[str, Any]


class ToolBody(BaseModel):
    params: dict[str, Any] = {}


def _web_dist() -> Path | None:
    """The built web UI (`etynt_gui/dist`). Env wins; otherwise walk up to the repo root."""
    if env := os.getenv("WEB_DIST"):
        return Path(env).resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "etynt_gui" / "dist"
        if candidate.is_dir():
            return candidate
    return None


def _graph_state(service: ContextBackend) -> str:
    """One connect round-trip — never a query, which would make health as heavy as work."""
    driver = getattr(service, "driver", None)
    if driver is None or not hasattr(driver, "verify_connectivity"):
        return "not_configured"
    try:
        driver.verify_connectivity()
    except Exception as exc:
        return f"error: {type(exc).__name__}"
    return "ok"


def _planner_state() -> str:
    """`ok` or the failure class. The planner is optional (ADR-0005) so this is a report,
    never a health failure: the deterministic keyword plan still answers."""
    host = os.environ.get("OLLAMA_HOST", OLLAMA_HOST).rstrip("/")
    try:
        httpx.get(f"{host}/api/tags", timeout=2.0).raise_for_status()
    except Exception as exc:
        return f"error: {type(exc).__name__}"
    return "ok"


def create_app(service: ContextBackend, web_dist: Path | None = None) -> FastAPI:
    """`service` is any ContextBackend: the routes never touch the corpus themselves.

    `web_dist` is a built static UI served at `/`. The UI stays its own project and only
    talks to `/v1/*`; with no build present the app is API-only."""
    app = FastAPI(title="Ety&T — Context Service", version="1.0")
    app.middleware("http")(request_logger())

    @app.get("/healthz")
    def healthz(response: Response) -> dict[str, Any]:
        """Liveness plus the two dependencies an answer needs; 503 when the graph is out.

        A constant `{"status": "ok"}` told an orchestrator nothing while every query
        failed, so the graph is now actually probed (#77). `planner_model` is reported
        but never fatal: the deterministic plan is the floor.
        """
        graph = _graph_state(service)
        healthy = graph in {"ok", "not_configured"}
        response.status_code = 200 if healthy else 503
        return {
            "status": "ok" if healthy else "degraded",
            "graph": graph,
            "planner_model": _planner_state(),
        }

    # response_model=None: the envelope is the contract, FastAPI must not reshape it.
    @app.post("/v1/query", response_model=None)
    def query(body: QueryBody) -> Any:
        return service.answer(
            body.question,
            as_of=body.as_of,
            status_in=body.status_in,
            token_budget=body.token_budget,
            effort=body.effort,
            detail=body.detail,
        )

    @app.post("/v1/plan", response_model=None)
    def plan(body: PlanBody) -> Any:
        """`source` is "model" or "deterministic": a question that names an identifier never
        reaches a model (ADR-0005), so a plan alone cannot tell parsed from understood."""
        return service.explain(body.question)

    @app.post("/v1/execute", response_model=None)
    def execute(body: ExecuteBody) -> Any:
        """Run an inspected plan. Cypher still comes from the compiler (ADR-0003)."""
        return service.execute(body.plan)

    @app.get("/v1/entity/{kind}/{key}", response_model=None)
    def entity(kind: str, key: str) -> Any:
        return service.entity(kind, key)

    @app.get("/v1/sources")
    def sources() -> list[dict[str, Any]]:
        return service.sources()

    @app.get("/v1/sources/{path:path}")
    def source(path: str) -> dict[str, Any]:
        for entry in service.sources():
            if entry["path"] == path or entry["path"].endswith("/" + path):
                return entry
        raise HTTPException(404, f"not indexed: {path}")

    @app.get("/v1/index/status")
    def index_status() -> dict[str, Any]:
        return service.index_status()

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, Any]:
        """Readiness without the planner probe: a graph is all the deterministic path needs."""
        graph = _graph_state(service)
        ready = graph in {"ok", "not_configured"}
        response.status_code = 200 if ready else 503
        return {"status": "ready" if ready else "not_ready", "graph": graph}

    @app.get("/v1/span")
    def span(
        path: str, start: int | None = None, end: int | None = None, region: str | None = None
    ) -> Response:
        """Text lines, or — for an image citation — the rectangle as PNG bytes."""
        if region is not None:
            try:
                x, y, w, h = (int(part) for part in region.split(","))
            except ValueError:
                raise HTTPException(400, "region must be x,y,w,h") from None
            try:
                content = service.spans.read_region(path, (x, y, w, h))
            except PermissionError:
                raise HTTPException(400, "path is not a readable file inside the corpus") from None
            except FileNotFoundError:
                raise HTTPException(404, "no such corpus file") from None
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            return Response(content=content, media_type="image/png")
        if start is None or end is None:
            raise HTTPException(400, "pass start and end, or a region")
        try:
            content = service.spans.read(path, start, end)
        except PermissionError:
            raise HTTPException(400, "path is not a readable file inside the corpus") from None
        except FileNotFoundError:
            raise HTTPException(404, "no such corpus file") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return Response(content=content, media_type="text/plain; charset=utf-8")

    # The demo surface: the same four tools the stdio MCP server registers, over HTTP.
    # Self-describing so the UI renders real parameters instead of a caption.
    @app.get("/v1/mcp")
    def mcp_tools() -> list[dict[str, Any]]:
        return [{"name": name, **spec} for name, spec in toolcall.TOOL_SPECS.items()]

    @app.post("/v1/mcp/{tool}", response_model=None)
    def mcp_call(tool: str, body: ToolBody) -> Any:
        if tool not in toolcall.TOOL_SPECS:
            raise HTTPException(404, f"unknown tool: {tool}")
        try:
            result = toolcall.call(service, tool, body.params)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"tool": tool, "params": body.params, "result": result}

    # Mounted last so /v1/* and /healthz are matched before the static files.
    web = web_dist or _web_dist()
    if web is not None and web.is_dir():
        print(f"web ui: {web}", file=sys.stderr, flush=True)
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    else:
        # A missing build looks like a dead server from the browser; say it on stdout.
        print("web ui: disabled (no dist) — run `make ui-build`", file=sys.stderr, flush=True)

    return app
