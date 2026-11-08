"""The transport-facing seam: anything with these members can back the HTTP and MCP adapters.

Nothing here may import `retrieval`, `graph` or `api` — a backend only has to answer
questions and turn a stored citation pointer back into bytes.
"""

from __future__ import annotations

from typing import Protocol


class SpanReader(Protocol):
    def read(self, pointer: str, start: int, end: int) -> bytes:
        """Lines [start, end], 1-indexed and inclusive; raises FileNotFoundError/PermissionError."""
        ...


class ContextBackend(Protocol):
    spans: SpanReader

    def answer(
        self,
        question: str,
        *,
        intent: str | None = None,
        as_of: str | None = None,
        status_in: list[str] | None = None,
        token_budget: int,
        effort: int | None = None,
        detail: str | None = None,
    ) -> dict:
        """The answer envelope, already budget-spent.

        `effort` is how hard to look (0-4); `detail` is how much comes back
        (`low`/`medium`/`high`). Transports default `detail` differently on purpose:
        REST keeps `medium`, MCP asks for `low`.
        """
        ...

    def plan(self, question: str, *, intent: str | None = None) -> dict:
        """The query plan, inspectable and unexecuted."""
        ...

    def explain(self, question: str, *, intent: str | None = None) -> dict:
        """The plan plus `source`/`detail`: whether a model typed it or a parser did."""
        ...

    def execute(self, plan: dict) -> dict:
        """Run a caller-supplied CQP; the plan is validated and compiled by the service."""
        ...

    def entity(self, kind: str, key: str) -> dict:
        """The answer envelope for one identity, matched exactly rather than by relevance."""
        ...

    def sources(self) -> list[dict]:
        """Every indexed root with its chunk count."""
        ...

    def index_status(self) -> dict:
        """Node counts for claims, chunks and sources."""
        ...
