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
        token_budget: int = 2000,
    ) -> dict:
        """The frozen answer envelope, already budget-spent."""
        ...

    def plan(self, question: str, *, intent: str | None = None) -> dict:
        """The query plan, inspectable and unexecuted."""
        ...
