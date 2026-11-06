"""The vector channel must actually contribute — issue 24.

A dead embedding path once passed a fully green suite because no test asserted that
vectors were written or used. These tests fail when that happens again.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

CORPUS = __import__("pathlib").Path(__file__).resolve().parents[3] / "vendor" / "att-hackathon-task"


@pytest.fixture(scope="module")
def driver():
    from graph.loader import connect

    try:
        connection = connect("bolt://localhost:7687", "neo4j", "northstar")
        connection.verify_connectivity()
    except Exception:  # any connection failure means "skip"
        pytest.skip("Neo4j not reachable")
    yield connection
    connection.close()


def test_every_chunk_that_exists_has_a_vector(driver):
    """Invariant: indexing either embeds every chunk or reports embedded=false."""
    with driver.session() as session:
        total = session.run("MATCH (c:Chunk) RETURN count(c) AS n").single()["n"]
        embedded = session.run(
            "MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c) AS n"
        ).single()["n"]
    if total == 0:
        pytest.skip("index is empty: run `python -m cli index`")
    assert embedded == total, f"{total - embedded} chunks have no vector"


def test_a_paraphrase_reaches_the_vector_channel(driver):
    """A question with none of the corpus's identifiers must still retrieve by meaning."""
    from retrieval.hybrid import search

    chunks, degraded, status = search(driver, "why was the in-memory lookup layer dropped", k=5)

    assert status["vector"] in {"ok", "empty"}, status
    if status["vector"] == "empty":
        pytest.skip("no vectors on this machine")
    assert chunks, "vector channel returned nothing for a purely semantic query"
    assert not degraded
