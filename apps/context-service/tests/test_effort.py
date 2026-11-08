"""The effort knob: how hard to look, and what that promise may and may not do.

The tests pin the two halves that matter. Higher effort widens recall (the semantic claim
channel) and stops when the promise is met; it never relaxes the gates, never invents a
claim, and an unreadable level is ignored instead of failing the request.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Self

import pytest

from retrieval import hybrid
from retrieval.cqp import CQP, Anchor, Intent
from retrieval.service import ContextService, _merge_claims, _overridden
from settings import CLAIM_INDEX, EFFORT_MAX

QUESTION = "what cases are we covering"


def _digest(root: Path, relative: str) -> str:
    return hashlib.sha256((root / relative).read_bytes()).hexdigest()


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "att-hackathon-task"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "cases.md").write_text(
        "# Support cases\n\nDate: 2026-07-01\nStatus: Accepted\n\nThe support team handles cases.\n"
    )
    return root


def citation(root: Path) -> dict:
    return {
        "path": "docs/cases.md",
        "start_line": 1,
        "end_line": 1,
        "hash": _digest(root, "docs/cases.md"),
        "lines": [1, 1],
    }


def claim_row(root: Path, claim_id: str = "c_1", **overrides) -> dict:
    row = {
        "id": claim_id,
        "subject": "support-team",
        "predicate": "MENTIONS",
        "polarity": "ASSERTS",
        "modality": "FACT",
        "status": "VALID",
        "confidence": 0.9,
        "valid_from": "2026-07-01",
        "valid_to": None,
        "observed_at": "2026-07-01",
        "citations": [citation(root)],
        "score": 0.8,
    }
    row.update(overrides)
    return row


class _Result:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, driver: RouteDriver) -> None:
        self.driver = driver

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_) -> None:
        return None

    def run(self, cypher: str, **params):
        # Only the claim channel is this double's concern: chunk kNN belongs to `_hybrid`,
        # and mixing the two made "did the semantic channel run" unanswerable.
        # The index name is a bound parameter, so the text of the query cannot tell the
        # channels apart — the parameter can.
        index = params.get("index")
        if index == CLAIM_INDEX:
            self.driver.semantic_calls.append(cypher)
            return _Result(self.driver.semantic)
        if index == "chunk_embedding":
            return _Result([])
        if "AS hits" in cypher:
            return _Result([])
        return _Result(self.driver.structural)


class RouteDriver:
    """Distinguishes the exact-graph query from the semantic one by their text."""

    def __init__(self, structural: list[dict], semantic: list[dict]) -> None:
        self.structural = structural
        self.semantic = semantic
        self.semantic_calls: list[str] = []

    def session(self) -> _Session:
        return _Session(self)


@pytest.fixture(autouse=True)
def stub_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hybrid, "_embed", lambda text: [0.01] * 768)


def test_effort_zero_never_pays_for_the_semantic_channel(corpus):
    driver = RouteDriver([], [claim_row(corpus)])

    result = ContextService(driver, corpus).answer(QUESTION, effort=0)

    assert driver.semantic_calls == []
    assert result["claims"] == []


def test_a_question_that_names_nothing_is_still_answered_by_meaning(corpus):
    """The whole point: no extracted term in the question, claims from the graph anyway."""
    driver = RouteDriver([], [claim_row(corpus), claim_row(corpus, "c_2", subject="cases-app")])

    result = ContextService(driver, corpus).answer(QUESTION)

    assert driver.semantic_calls, "the semantic channel must run at the automatic level"
    assert len(result["claims"]) == 2
    assert any("Widened by meaning" in gap for gap in result["gaps"])


def test_widening_stops_once_the_promise_is_met(corpus):
    driver = RouteDriver([], [claim_row(corpus)])

    result = ContextService(driver, corpus).answer(QUESTION, effort=1)

    assert driver.semantic_calls, "one claim satisfies effort 1's promise of one"
    assert len(result["claims"]) == 1


def test_a_met_promise_costs_nothing(corpus):
    driver = RouteDriver([claim_row(corpus)], [claim_row(corpus, "c_2")])

    result = ContextService(driver, corpus).answer(QUESTION, effort=1)

    assert driver.semantic_calls == []
    assert len(result["claims"]) == 1


def test_an_unmet_promise_is_reported_not_dressed_up(corpus):
    driver = RouteDriver([], [claim_row(corpus)])

    result = ContextService(driver, corpus).answer(QUESTION, effort=EFFORT_MAX)

    assert len(result["claims"]) == 1, "effort may not invent the missing claims"
    assert any("Widened by meaning: 1" in gap for gap in result["gaps"])


def test_the_semantic_channel_is_silent_when_the_model_is_absent(corpus, monkeypatch):
    monkeypatch.setattr(hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no model")))
    driver = RouteDriver([], [claim_row(corpus)])

    result = ContextService(driver, corpus).answer(QUESTION)

    assert result["claims"] == [], "no model, no semantic claims: silence, not invention"
    assert any("vector" in gap for gap in result["gaps"]), "the missing channel is named"


def test_effort_override_clamps_and_ignores_garbage():
    base = CQP(intent=Intent.LOOKUP, anchors=[Anchor(key="cases")], effort=2)

    assert _overridden(base, None, None, 100, 9).effort == EFFORT_MAX
    assert _overridden(base, None, None, 100, -3).effort == 0
    assert _overridden(base, None, None, 100, "hard").effort == base.effort
    assert _overridden(base, None, None, 100, None).effort == base.effort


def test_merging_the_same_fact_joins_its_citations():
    first = {"statement": "a OWNS b", "status": "VALID", "citations": [{"path": "x.md"}]}
    second = {"statement": "a OWNS b", "status": "VALID", "citations": [{"path": "y.md"}]}

    merged = _merge_claims([first], [second])

    assert len(merged) == 1
    assert [c["path"] for c in merged[0]["citations"]] == ["x.md", "y.md"]
