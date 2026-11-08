"""The vocabulary resolver, without a database or a model.

What is asserted here is the contract that makes the resolver safe: it proposes, it never
invents, and every failure path returns the deterministic plan instead of an error.
"""

from __future__ import annotations

from graph import vocab
from retrieval.cqp import CQP, Anchor, Intent, Traverse

VECTOR = [0.01] * 768


class QueryResult:
    def __init__(self, records):
        self.records = records


class FakeDriver:
    def __init__(self, records=None):
        self.records = records or []
        self.calls: list[tuple[str, dict]] = []

    def execute_query(self, query, **params):
        self.calls.append((query, params))
        return QueryResult(self.records)


def test_build_embeds_every_key_and_every_gloss():
    driver = FakeDriver([{"key": "inventory-service", "kind": "Service"}, {"key": "users", "kind": "Table"}])
    seen: list[str] = []

    def embed(text: str) -> list[float]:
        seen.append(text)
        return VECTOR

    written = vocab.build(driver, embed)

    assert written == 2 + len(vocab.PREDICATE_GLOSSES)
    assert "inventory-service" in seen
    assert "which fields or columns a table has" in seen
    _, params = driver.calls[-1]
    assert {row["source"] for row in params["vocab"]} == {"entity", "predicate"}
    assert all("text" not in row for row in params["vocab"]), "only the vector is stored, not the gloss"


def test_resolve_splits_entities_from_predicates():
    driver = FakeDriver(
        [
            {"term": "users", "kind": "Table", "source": "entity", "score": 0.91},
            {"term": "HAS_COLUMN", "kind": "PREDICATE", "source": "predicate", "score": 0.80},
        ]
    )

    assert vocab.resolve(driver, "what fields does the users table have", lambda _: VECTOR) == (
        ["users"],
        ["HAS_COLUMN"],
    )


def test_resolve_returns_none_rather_than_raising_without_a_model():
    assert vocab.resolve(FakeDriver(), "anything", lambda _: (_ for _ in ()).throw(RuntimeError("no model"))) is None


def test_resolve_returns_none_when_the_index_does_not_exist_yet():
    class MissingIndex(FakeDriver):
        def execute_query(self, query, **params):
            raise RuntimeError("There is no procedure with the name `db.index.vector.queryNodes`")

    assert vocab.resolve(MissingIndex(), "anything", lambda _: VECTOR) is None


def test_service_prefers_the_vocabulary_when_it_is_enabled(monkeypatch):
    from retrieval import service as service_module

    monkeypatch.setattr(service_module, "VOCAB_RESOLVE", True)
    monkeypatch.setattr(vocab, "resolve", lambda driver, question, embed: (["users"], ["HAS_COLUMN"]))
    plan = CQP(intent=Intent.LOOKUP, anchors=[Anchor(kind="ANY", key="fields", match="exact")],
               traverse=Traverse(predicates=["OWNS"]))

    resolved = service_module.ContextService(FakeDriver(), ".")._resolved(
        plan, "what fields does the users table have"
    )

    assert [(a.kind, a.key) for a in resolved.anchors] == [("ANY", "users")]
    assert resolved.traverse.predicates == ["OWNS"], "predicates stay with the ontology cues"


def test_service_ignores_the_vocabulary_when_it_is_disabled(monkeypatch):
    """The shipped default: measured 4/7 against the traps, so opt-in only."""
    from retrieval import service as service_module

    monkeypatch.setattr(service_module, "VOCAB_RESOLVE", False)
    called: list[str] = []
    monkeypatch.setattr(vocab, "resolve", lambda driver, question, embed: called.append(question) or (["users"], []))
    plan = CQP(intent=Intent.LOOKUP, anchors=[Anchor(kind="ANY", key="fields", match="exact")])

    assert service_module.ContextService(FakeDriver(), ".")._resolved(plan, "q").anchors[0].key == "fields"
    assert called == []


def test_service_falls_back_to_the_attested_plan_when_nothing_resolves(monkeypatch):
    from retrieval.service import ContextService

    monkeypatch.setattr(vocab, "resolve", lambda driver, question, embed: None)
    monkeypatch.setattr(ContextService, "_attested", lambda self, plan: plan.model_copy(update={"intent": Intent.RISKS}))
    plan = CQP(intent=Intent.LOOKUP, anchors=[Anchor(kind="ANY", key="x", match="exact")])

    assert ContextService(FakeDriver(), ".")._resolved(plan, "x").intent is Intent.RISKS


def test_build_writes_nothing_when_the_model_returns_no_vector():
    driver = FakeDriver([{"key": "users", "kind": "Table"}])

    assert vocab.build(driver, lambda _: None) == 0
    assert driver.calls == [driver.calls[0]] or all("UNWIND $vocab" not in q for q, _ in driver.calls)
