"""FastAPI transport. Routes translate HTTP into ContextBackend calls; no rules live here."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import toolcall
from models.protocols import ContextBackend


class QueryBody(BaseModel):
    question: str
    as_of: str | None = None
    status_in: list[str] | None = None
    token_budget: int = 2000


class PlanBody(BaseModel):
    question: str


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


def create_app(service: ContextBackend, web_dist: Path | None = None) -> FastAPI:
    """`service` is any ContextBackend: the routes never touch the corpus themselves.

    `web_dist` is a built static UI served at `/`. The UI stays its own project and only
    talks to `/v1/*`; with no build present the app is API-only."""
    app = FastAPI(title="Ety&T — Context Service", version="1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # response_model=None: the envelope is the contract, FastAPI must not reshape it.
    @app.post("/v1/query", response_model=None)
    def query(body: QueryBody) -> Any:
        return service.answer(
            body.question,
            as_of=body.as_of,
            status_in=body.status_in,
            token_budget=body.token_budget,
        )

    @app.post("/v1/plan", response_model=None)
    def plan(body: PlanBody) -> Any:
        return service.plan(body.question)

    @app.get("/v1/span")
    def span(path: str, start: int, end: int) -> Response:
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
