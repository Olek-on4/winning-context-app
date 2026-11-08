"""The opt-in vocabulary path, end to end against a real graph — shape only.

The measurement in docs/06 says this path answers worse than corpus attestation on the
seven traps, so nothing here asserts its answers. What it must prove is the contract that
makes the flag safe to flip: with `ETYT_VOCAB_RESOLVE=1` every question still produces the
frozen envelope, never an exception and never a missing key.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from retrieval import service as service_module

REPO = Path(__file__).resolve().parents[4]
CORPUS = REPO / "vendor" / "att-hackathon-task"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_service():
    """A real driver; skip when the store or the vocabulary is not there."""
    neo4j = pytest.importorskip("neo4j")
    from sources import SpanStore, discover

    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    driver = neo4j.GraphDatabase.driver(uri, auth=(os.getenv("NEO4J_USER", "neo4j"),
                                                  os.getenv("NEO4J_PASSWORD", "etyt-context")))
    try:
        driver.verify_connectivity()
    except Exception:
        pytest.skip("no graph to resolve against")
    try:
        count = driver.execute_query("MATCH (v:Vocab) RETURN count(v) AS n").records[0]["n"]
    except Exception:
        count = 0
    if not count:
        pytest.skip("vocabulary is empty: run `cli index` with a model")
    if not CORPUS.is_dir():
        pytest.skip("corpus submodule is not checked out")
    yield service_module.ContextService(driver, SpanStore(discover([CORPUS])))
    driver.close()


@pytest.fixture(autouse=True)
def enable_vocab(monkeypatch):
    monkeypatch.setattr(service_module, "VOCAB_RESOLVE", True)


def test_flag_path_returns_the_frozen_envelope(live_service):
    result = live_service.answer("What fields does the users table have?")

    assert set(result) == {
        "answer",
        "detail",
        "claims",
        "conflicts",
        "gaps",
        "degraded",
        "evidence",
    }
    assert isinstance(result["answer"], str)
    for claim in result["claims"]:
        assert set(claim) == {
            "statement", "status", "valid_from", "valid_to", "confidence",
            "superseded_by", "citations",
        }
        assert claim["citations"], "a claim without a pointer is not evidence"


def test_flag_path_still_degrades_rather_than_raising(live_service, monkeypatch):
    monkeypatch.setattr(
        service_module.hybrid, "_embed", lambda text: (_ for _ in ()).throw(RuntimeError("no model"))
    )

    result = live_service.answer("Is the PaymentService in the payment flow?")

    assert set(result) == {
        "answer",
        "detail",
        "claims",
        "conflicts",
        "gaps",
        "degraded",
        "evidence",
    }
    assert result["claims"] or result["gaps"], "an empty answer must say why"
