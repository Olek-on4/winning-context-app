"""Assembly and fusion without a database: a stub driver is the whole fixture."""

from __future__ import annotations

import hashlib

import pytest

from retrieval import hybrid, planner
from retrieval.cqp import CQP
from retrieval.service import ContextService

QUESTION = "what does inventory-service read from"


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    def unavailable(question: str):
        raise RuntimeError("no model in tests")

    monkeypatch.setattr(planner, "_from_model", unavailable)
    # The service searches when the graph comes back empty; a unit test must never reach
    # Ollama. Channel-behaviour tests override this with their own stub.
    monkeypatch.setattr(
        hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no embed"))
    )


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


@pytest.fixture(autouse=True)
def working_embedder(monkeypatch):
    """The vector channel is a normal channel: only tests about its absence break it."""
    monkeypatch.setattr(hybrid, "_embed", lambda text: [0.0] * 768)


class FakeSession:
    def __init__(self, rows, chunks=()):
        self.rows = rows
        self.chunks = list(chunks)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        # Chunk search is a different channel with a different result shape: answering it
        # with claim rows makes every answer look degraded.
        if "db.index" in query or "db.index.fulltext" in query:
            # A row may declare which channel returns it; default: both, as a healthy
            # index would. Without this the double cannot test corroboration.
            wanted = "bm25" if "fulltext" in query else "vector"
            return [row for row in self.chunks if row.get("channel", wanted) == wanted]
        return list(self.rows)


class FakeDriver:
    def __init__(self, rows, chunks=()):
        self.rows = rows
        self.chunks = chunks
        self.sessions = []

    def session(self):
        session = FakeSession(self.rows, self.chunks)
        self.sessions.append(session)
        return session


class BrokenDriver:
    def session(self):
        raise RuntimeError("graph down")


def chunk_hit(root, relative="docs/adr/003-stock-cache.md", lines=(6, 6), score=0.9):
    """One row shaped like the chunk index returns, so the channel is genuinely healthy."""
    return {
        "node": {
            "text": "Remove Redis from the local inventory path before the next release.",
            "path": relative,
            "heading": "Remove the stock read cache",
            "start_line": lines[0],
            "end_line": lines[1],
            "hash": digest(root, relative),
        },
        "score": score,
        "path": relative,
    }


def test_envelope_and_claim_shape_are_exact(corpus):
    driver = FakeDriver(
        [row("c_1", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)))],
        chunks=[chunk_hit(corpus)],
    )
    result = ContextService(driver, corpus).answer(QUESTION, intent="LOOKUP")

    assert set(result) == {
        "answer",
        "detail",
        "claims",
        "conflicts",
        "gaps",
        "degraded",
        "evidence",
    }
    assert result["detail"] == "medium"
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
        "why_not_valid",
        "id",
        "subject",
        "predicate",
        "polarity",
    ]
    assert claim["statement"] == "inventory-service READS_FROM"
    assert claim["citations"] == [
        {
            "path": "docs/adr/003-stock-cache.md",
            "lines": [6, 6],
            "hash": digest(corpus, "docs/adr/003-stock-cache.md"),
        }
    ]


def test_answer_names_a_claim_that_is_neither_valid_nor_superseded(corpus):
    """A DISPUTED-only hit used to answer "No validated claims matched the question"
    beside a one-element `claims` array — the answer contradicting the evidence."""
    rows = [row("c_1", citation(corpus, "wiki/inventory-service.md", (5, 5)), status="DISPUTED")]
    result = ContextService(FakeDriver(rows), corpus).answer(QUESTION, intent="LOOKUP")

    assert len(result["claims"]) == 1
    assert result["answer"].startswith("Disputed: ")


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
    # #80: one representation — the successor's claim id, never its citation path.
    assert deprecated[0]["superseded_by"] == "c_new"


def test_supersession_ignores_another_subject_sharing_the_predicate(corpus):
    """#72: every service READS_FROM something, so a successor matched on the predicate
    alone pointed a claim at an unrelated subject's claim."""
    rows = [
        row(
            "c_old",
            citation(corpus, "wiki/inventory-service.md", (5, 5)),
            status="DEPRECATED",
            valid_from="2026-01-01",
            valid_to="2026-06-04",
        ),
        row("c_billing", citation(corpus, "docs/adr/003-stock-cache.md", (2, 2)),
            subject="billing-service", valid_from="2026-06-05"),
    ]
    result = ContextService(FakeDriver(rows), corpus).answer(QUESTION, intent="TIMELINE")

    deprecated = [c for c in result["claims"] if c["status"] == "DEPRECATED"]
    assert deprecated[0]["superseded_by"] is None


def test_supersession_tie_breaks_on_the_lowest_claim_id(corpus):
    """#80: two successors on the same date. The rule is earliest `valid_from`, then the
    lowest claim id — the same rule the TIMELINE template applies in Cypher."""
    rows = [
        row(
            "c_old",
            citation(corpus, "wiki/inventory-service.md", (5, 5)),
            status="DEPRECATED",
            valid_from="2026-01-01",
            valid_to="2026-06-04",
        ),
        row("c_beta", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)),
            object="sqlite", valid_from="2026-06-04"),
        row("c_alpha", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)),
            object="redis", valid_from="2026-06-04"),
    ]
    result = ContextService(FakeDriver(rows), corpus).answer(QUESTION, intent="TIMELINE")

    deprecated = [c for c in result["claims"] if c["status"] == "DEPRECATED"]
    assert deprecated[0]["superseded_by"] == "c_alpha"


def test_token_budget_bounds_the_answer_and_flags_it(corpus):
    """#76: the answer was assembled before the budget was spent, so a long answer ran
    over the budget in full and nothing said so."""
    rows = [
        row(f"c_{index}", citation(corpus, "docs/adr/003-stock-cache.md", (6, 6)), object=f"target-{index}")
        for index in range(4)
    ]
    result = ContextService(FakeDriver(rows), corpus).answer(
        QUESTION, intent="LOOKUP", token_budget=12
    )

    assert len(result["answer"]) <= 12 * 4
    assert result["answer"].endswith("…")
    assert result["degraded"] is True
    assert any(gap.startswith("Response truncated") for gap in result["gaps"])


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

    # The first call is the anchor attestation, which opens its own session; the compiled
    # query is the one carrying the compiler's parameters.
    params = [p for session in driver.sessions for _, p in session.calls if "anchor_keys" in p][-1]
    assert params["anchor_keys"] == ["inventory-service"]
    assert params["as_of"] == "2026-03-01"
    assert params["status_in"] == ["VALID", "DEPRECATED"]


def test_plan_returns_a_validated_cqp_and_executes_nothing(corpus):
    driver = FakeDriver([])
    plan = ContextService(driver, corpus).plan("how do inventory-service and Redis connect")

    assert plan["cqp_version"] == "1.0"
    assert plan["intent"] == "RELATIONSHIP"
    assert plan["anchors"][0]["key"] == "inventory-service"
    assert plan["traverse"]["max_nodes"] == 50
    assert "max_hops" not in plan["traverse"]
    assert driver.sessions == []


def test_execution_failure_degrades_instead_of_raising(corpus, monkeypatch):
    monkeypatch.setattr(hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no embed")))
    result = ContextService(BrokenDriver(), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["degraded"] is True
    assert result["claims"] == []
    assert any("Graph query failed" in gap for gap in result["gaps"])


def test_graph_failure_searches_once_and_reports_one_gap_set(corpus, monkeypatch):
    """#78: a failed graph query ran the hybrid search in the failure branch *and* again
    in the empty-rows branch, so one request produced two contradictory gap sets."""
    monkeypatch.setattr(hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no embed")))
    calls: list[str] = []
    real = hybrid.search

    def counting(driver, text, k=10):
        calls.append(text)
        return real(driver, text, k)

    monkeypatch.setattr(hybrid, "search", counting)
    result = ContextService(BrokenDriver(), corpus).answer(QUESTION, intent="LOOKUP")

    assert len(calls) == 1
    assert sum("Graph query failed" in gap for gap in result["gaps"]) == 1
    assert sum("Search channel unavailable" in gap for gap in result["gaps"]) == 1
    assert not any("No claims matched" in gap for gap in result["gaps"]), result["gaps"]


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


def test_no_claims_and_no_passages_is_reported_as_such(corpus):
    """An empty answer distinguishes "nothing here" from "a channel broke"."""
    service = ContextService(FakeDriver([]), corpus)
    result = service.answer(QUESTION, intent="LOOKUP")

    assert result["claims"] == []
    assert result["evidence"] == []
    assert any("No claims matched" in gap for gap in result["gaps"])


def test_envelope_names_the_channel_that_failed(corpus, monkeypatch):
    """A user reading `gaps` must be able to tell a smaller answer from a broken one."""
    monkeypatch.setattr(
        hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no embed"))
    )

    result = ContextService(FakeDriver([]), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["degraded"] is True
    assert any("Search channel unavailable: vector" in gap for gap in result["gaps"])


def test_explain_reports_a_model_typed_plan(monkeypatch):
    """The one thing an operator needs from /v1/plan: did a model understand this?"""
    from retrieval import planner

    monkeypatch.setattr(
        planner,
        "_from_model",
        lambda question: planner.CQP(
            intent=planner.Intent.LOOKUP, anchors=[planner.Anchor(kind="Table", key="users")]
        ),
    )

    explained = ContextService(FakeDriver([]), ".").explain("what holds the customer records")

    assert explained["source"] == "model"
    assert explained["anchors"][0]["kind"] == "Table"


def test_plan_stays_a_pure_cqp_so_answer_can_revalidate_it(corpus):
    """`answer()` round-trips this dict through CQP.model_validate, which forbids extras."""
    plan = ContextService(FakeDriver([]), corpus).plan(QUESTION)

    assert "source" not in plan
    assert CQP.model_validate(plan).anchors, "the plan must still parse as a CQP"


def test_a_chunk_hit_becomes_cited_evidence_not_a_gap(corpus):
    """The layer under claims: most of a corpus is prose no extractor turned into a triple."""
    result = ContextService(FakeDriver([], chunks=[chunk_hit(corpus)]), corpus).answer(
        QUESTION, intent="LOOKUP"
    )

    assert result["claims"] == []
    assert len(result["evidence"]) == 1
    passage = result["evidence"][0]
    assert passage["path"] == "docs/adr/003-stock-cache.md"
    assert passage["lines"] == [6, 6]
    assert passage["heading"] == "Remove the stock read cache"
    # Corpus text reaches a caller inside the trust boundary, never bare (AGENTS.md #3).
    assert passage["text"].startswith(
        '<untrusted_source path="docs/adr/003-stock-cache.md">'
    )
    assert "Remove Redis" in passage["text"]
    assert passage["text"].endswith("</untrusted_source>")
    assert passage["hash"], "evidence without a hash is not evidence"


def test_evidence_that_fails_hash_verification_is_dropped(corpus):
    """Same anti-hallucination rule as a citation: the bytes must be the bytes."""
    tampered = chunk_hit(corpus)
    tampered["node"]["hash"] = "0" * 64

    result = ContextService(FakeDriver([], chunks=[tampered]), corpus).answer(
        QUESTION, intent="LOOKUP"
    )

    assert result["evidence"] == []
    assert any("none survived verification" in gap for gap in result["gaps"])


def test_effort_zero_returns_no_evidence_at_all(corpus):
    driver = FakeDriver([], chunks=[chunk_hit(corpus)])

    result = ContextService(driver, corpus).answer(QUESTION, intent="LOOKUP", effort=0)

    assert result["evidence"] == []
    assert not [call for call in driver.sessions[0].calls if "db.index" in call[0]]


def test_evidence_is_capped_by_effort(corpus):
    # Distinct line ranges, because identical path+lines is one passage, not eight.
    chunks = [chunk_hit(corpus, lines=(i + 1, i + 1), score=0.9 - i / 100) for i in range(5)]

    low = ContextService(FakeDriver([], chunks=chunks), corpus).answer(QUESTION, intent="LOOKUP", effort=1)
    high = ContextService(FakeDriver([], chunks=chunks), corpus).answer(QUESTION, intent="LOOKUP", effort=4)

    assert len(low["evidence"]) == 2
    assert len(high["evidence"]) == 5, "level 4 may carry more passages than level 1"


def test_a_passage_without_relevance_is_not_evidence(corpus):
    """A keyword hit that shares no content word with the question is coincidence."""
    unrelated = chunk_hit(corpus, relative="docs/adr/003-stock-cache.md")
    unrelated["node"]["text"] = "Unrelated boilerplate about a completely different matter entirely."
    unrelated["score"] = 0.2
    unrelated["channel"] = "bm25"  # keyword hit only, sharing no word: coincidence

    result = ContextService(FakeDriver([], chunks=[unrelated]), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["evidence"] == []


def test_meaning_alone_is_not_evidence_but_agreement_is(corpus):
    """Measured: cosine scores noise and signal alike, so one channel cannot be trusted."""
    semantic = chunk_hit(corpus)
    # Deliberately shares no word with the question: only corroboration may admit it.
    semantic["node"]["text"] = (
        "The read path went through a cache layer, so numbers came back without touching "
        "the primary store at all."
    )
    semantic["node"]["heading"] = "Availability"

    agreed = [{**semantic, "channel": "bm25"}, {**semantic, "channel": "vector"}]
    both = ContextService(FakeDriver([], chunks=agreed), corpus).answer(
        "how is stock availability answered quickly", intent="LOOKUP"
    )
    vector_only = ContextService(
        FakeDriver([], chunks=[{**semantic, "channel": "vector"}]), corpus
    ).answer("how is stock availability answered quickly", intent="LOOKUP")

    assert len(both["evidence"]) == 1, "keyword and meaning agreeing is evidence"
    assert vector_only["evidence"] == [], "meaning alone is not"


def test_evidence_is_spent_inside_the_token_budget(corpus):
    """A client sizing its context from token_budget must not receive a surprise."""
    result = ContextService(FakeDriver([], chunks=[chunk_hit(corpus)]), corpus).answer(
        QUESTION, intent="LOOKUP", token_budget=1
    )

    assert result["evidence"] == []
    assert any("truncated" in gap for gap in result["gaps"])


def test_the_indexed_digest_is_what_evidence_verifies_against(corpus):
    """Verifying against a hash we just recomputed proves nothing (F12).

    The chunk row carries the digest recorded at index time; a passage whose recorded digest
    no longer matches the file must be dropped, not re-blessed with the live one.
    """
    stale = chunk_hit(corpus)
    stale["node"]["hash"] = "1" * 64  # indexed when the file was different

    result = ContextService(FakeDriver([], chunks=[stale]), corpus).answer(QUESTION, intent="LOOKUP")

    assert result["evidence"] == []


def test_hybrid_queries_project_a_digest(corpus):
    """Without the projection the chunk row's hash is empty and verification is vacuous."""
    from retrieval import hybrid

    for cypher in (hybrid._BM25, hybrid._VECTOR):
        assert "AS hash" in cypher
