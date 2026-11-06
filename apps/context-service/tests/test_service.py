"""Assembly and fusion without a database: a stub driver is the whole fixture."""

from __future__ import annotations

import hashlib

import pytest

from retrieval import hybrid, planner
from retrieval.service import ContextService

QUESTION = "what does inventory-service read from"


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    def unavailable(question: str):
        raise RuntimeError("no model in tests")

    monkeypatch.setattr(planner, "_from_model", unavailable)


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "att-hackathon-task"
    (root / "wiki").mkdir(parents=True)
    (root / "docs" / "adr").mkdir(parents=True)
    (root / "wiki" / "inventory-service.md").write_text(
        "# Stock / inventory-service\n\nCore Platform handbook · 2026-02-17\n\n"
        "Core Platform owns Stock and its Redis read cache.\n"
    )
    (root / "docs" / "adr" / "003-stock-cache.md").write_text(
        "# Remove the stock read cache\n\nDate: 2026-06-04\nStatus: Accepted\n\n"
        "Remove Redis from the local inventory path.\n"
    )
    return root


def digest(root, relative: str) -> str:
    return hashlib.sha256((root / relative).read_bytes()).hexdigest()


def citation(root, relative: str, lines=(1, 1), stored: str | None = None) -> dict:
    return {
        "path": relative,
        "start_line": lines[0],
        "end_line": lines[1],
        "hash": digest(root, relative) if stored is None else stored,
    }


def row(claim_id: str, citation_item: dict, **overrides) -> dict:
    base = {
        "id": claim_id,
        "subject": "inventory-service",
        "predicate": "READS_FROM",
        "polarity": "ASSERTS",
        "modality": "FACT",
        "status": "VALID",
        "confidence": 0.9,
        "valid_from": "2026-06-04",
        "valid_to": None,
        "observed_at": "2026-06-04",
        "citations": [citation_item],
    }
    base.update(overrides)
    return base


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return list(self.rows)


class FakeDriver:
    def __init__(self, rows):
        self.rows = rows
        self.sessions = []

    def session(self):
        session = FakeSession(self.rows)
        self.sessions.append(session)
        return session


class BrokenDriver:
    def session(self):
        raise RuntimeError("graph down")


def test_envelope_and_claim_shape_are_exact(corpus):
    driver = FakeDriver([row("c_1", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)))])
    result = ContextService(driver, corpus).answer(QUESTION, intent="LOOKUP")

    assert set(result) == {"answer", "claims", "conflicts", "gaps", "degraded"}
    assert result["degraded"] is False
    claim = result["claims"][0]
    assert list(claim) == [
        "statement",
        "status",
        "valid_from",
        "valid_to",
        "confidence",
        "superseded_by",
        "citations",
    ]
    assert claim["statement"] == "inventory-service READS_FROM"
    assert claim["citations"] == [
        {
            "path": "docs/adr/003-stock-cache.md",
            "lines": [6, 6],
            "hash": digest(corpus, "docs/adr/003-stock-cache.md"),
        }
    ]


def test_duplicate_rows_dedup_and_merge_their_citations(corpus):
    rows = [
        row("c_1", citation(corpus, "wiki/inventory-service.md", (5, 5))),
        row("c_1", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6))),
    ]
    result = ContextService(FakeDriver(rows), corpus).answer(QUESTION, intent="LOOKUP")

    assert len(result["claims"]) == 1
    assert [(c["path"], c["lines"]) for c in result["claims"][0]["citations"]] == [
        ("wiki/inventory-service.md", [5, 5]),
        ("docs/adr/003-stock-cache.md", [6, 6]),
    ]


def test_hash_mismatch_drops_the_citation_and_the_unbacked_claim(corpus):
    bad = citation(corpus, "wiki/inventory-service.md", (5, 5), stored="0" * 12)
    result = ContextService(FakeDriver([row("c_1", bad)]), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["claims"] == []
    assert any("hash verification" in gap for gap in result["gaps"])


def test_out_of_range_lines_are_rejected(corpus):
    bad = citation(corpus, "wiki/inventory-service.md", (40, 41))
    result = ContextService(FakeDriver([row("c_1", bad)]), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["claims"] == []
    assert any("outside the file" in gap for gap in result["gaps"])


def test_disputed_rows_become_a_conflict(corpus):
    rows = [
        row("c_a", citation(corpus, "wiki/inventory-service.md", (5, 5)), status="DISPUTED"),
        row(
            "c_b",
            citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)),
            status="DISPUTED",
            polarity="NEGATES",
        ),
    ]
    result = ContextService(FakeDriver(rows), corpus).answer(QUESTION, intent="CONFLICTS")

    assert result["conflicts"] == [
        {
            "a": "inventory-service NOT READS_FROM",
            "b": "inventory-service READS_FROM",
            "note": "Sources disagree; the resolver found no winner.",
        }
    ]


def test_timeline_points_a_deprecated_claim_at_its_successor(corpus):
    rows = [
        row(
            "c_old",
            citation(corpus, "wiki/inventory-service.md", (5, 5)),
            status="DEPRECATED",
            valid_from="2026-01-01",
            valid_to="2026-06-04",
        ),
        row(
            "c_new",
            citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)),
            valid_from="2026-06-04",
        ),
    ]
    result = ContextService(FakeDriver(rows), corpus).answer(QUESTION, intent="TIMELINE")

    deprecated = [c for c in result["claims"] if c["status"] == "DEPRECATED"]
    assert deprecated[0]["superseded_by"] == "docs/adr/003-stock-cache.md"


def test_token_budget_drops_claims_but_keeps_the_answer(corpus):
    rows = [row("c_1", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)))]
    result = ContextService(FakeDriver(rows), corpus).answer(
        QUESTION, intent="LOOKUP", token_budget=1
    )

    assert result["claims"] == []
    assert result["answer"]
    assert result["gaps"][0].startswith("Response truncated")


def test_request_overrides_reach_the_query_parameters(corpus):
    driver = FakeDriver([row("c_1", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)))])
    ContextService(driver, corpus).answer(
        "does inventory-service still use Redis",
        intent="STATE_OF",
        as_of="2026-03-01",
        status_in=["VALID", "DEPRECATED"],
    )

    _, params = driver.sessions[0].calls[0]
    assert params["anchor_keys"] == ["inventory-service"]
    assert params["as_of"] == "2026-03-01"
    assert params["status_in"] == ["VALID", "DEPRECATED"]


def test_plan_returns_a_validated_cqp_and_executes_nothing(corpus):
    driver = FakeDriver([])
    plan = ContextService(driver, corpus).plan("how do inventory-service and Redis connect")

    assert plan["cqp_version"] == "1.0"
    assert plan["intent"] == "RELATIONSHIP"
    assert plan["anchors"][0]["key"] == "inventory-service"
    assert plan["traverse"]["max_hops"] == 2
    assert driver.sessions == []


def test_execution_failure_degrades_instead_of_raising(corpus, monkeypatch):
    monkeypatch.setattr(hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no embed")))
    result = ContextService(BrokenDriver(), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["degraded"] is True
    assert result["claims"] == []
    assert any("Graph query failed" in gap for gap in result["gaps"])


class IndexDriver:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def session(self):
        return self

    def run(self, query, **params):
        if "fulltext" in query:
            return [
                {
                    "node": {"text": "redis cache", "path": "wiki/a.md", "start_line": 5, "end_line": 5},
                    "score": 2.0,
                }
            ]
        return [
            {
                "node": {"text": "redis removal", "path": "docs/b.md", "start_line": 6, "end_line": 6},
                "score": 0.9,
            }
        ]


def test_hybrid_fuses_bm25_and_vector_with_rrf(monkeypatch):
    monkeypatch.setattr(hybrid, "_embed", lambda text: [0.0] * 768)

    chunks, degraded, status = hybrid.search(IndexDriver(), "redis", k=5)

    assert degraded is False
    assert status == {"bm25": "ok", "vector": "ok"}
    assert {chunk["via"] for chunk in chunks} == {"bm25", "vector"}
    assert all(chunk["score"] > 0 for chunk in chunks)
    assert [chunk["path"] for chunk in chunks] == ["docs/b.md", "wiki/a.md"]


def test_dead_vector_channel_is_reported_not_hidden(monkeypatch):
    """The embedding failure that shipped silently: BM25 answers, so `degraded` stayed
    false and the vector index could be empty for days without anyone noticing."""
    monkeypatch.setattr(
        hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no embed"))
    )

    chunks, degraded, status = hybrid.search(IndexDriver(), "redis", k=5)

    assert chunks, "the lexical channel still answers"
    assert status == {"bm25": "ok", "vector": "error"}
    assert degraded is True


def test_hybrid_with_no_index_data_is_degraded(monkeypatch):
    monkeypatch.setattr(hybrid, "_embed", lambda text: [0.0] * 768)

    class EmptyDriver(IndexDriver):
        def run(self, query, **params):
            return []

    assert hybrid.search(EmptyDriver(), "redis") == ([], True, {"bm25": "empty", "vector": "empty"})


def test_empty_graph_falls_back_to_evidence_candidates_not_claims(corpus):
    """A chunk is a lead, never a claim: no claims, but the gap names where to look."""
    service = ContextService(FakeDriver([]), corpus)
    result = service.answer(QUESTION, intent="LOOKUP")

    assert result["claims"] == []
    assert any("evidence candidates" in gap or "No claims matched" in gap for gap in result["gaps"])


def test_envelope_names_the_channel_that_failed(corpus, monkeypatch):
    """A user reading `gaps` must be able to tell a smaller answer from a broken one."""
    monkeypatch.setattr(
        hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no embed"))
    )

    result = ContextService(FakeDriver([]), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["degraded"] is True
    assert any("Search channel unavailable: vector" in gap for gap in result["gaps"])
