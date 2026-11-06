"""FastAPI transport. Routes translate HTTP into ContextBackend calls; no rules live here."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from models.protocols import ContextBackend


class QueryBody(BaseModel):
    question: str
    as_of: str | None = None
    status_in: list[str] | None = None
    token_budget: int = 2000


class PlanBody(BaseModel):
    question: str


def create_app(service: ContextBackend) -> FastAPI:
    """`service` is any ContextBackend: the routes never touch the corpus themselves."""
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

    return app
