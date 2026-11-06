"""The compiler is pure: six templates, parameters only, caps clamped, nothing writable."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from retrieval.cqp import CQP, MAX_HOPS, MAX_NODES, Intent, compile, validate_plan

ALL_INTENTS = list(Intent)


def make_plan(intent: Intent, **overrides) -> CQP:
    payload = {
        "intent": intent.value,
        "anchors": [{"kind": "Service", "key": "inventory-service", "match": "exact"}],
    }
    payload.update(overrides)
    return validate_plan(payload)


@pytest.mark.parametrize("intent", ALL_INTENTS)
def test_every_intent_compiles_to_a_parameterised_read_only_query(intent):
    cypher, params = compile(make_plan(intent))

    assert cypher.startswith("MATCH")
    assert "$anchor_keys" in cypher
    assert "inventory-service" not in cypher
    assert re.findall(r"\$(\w+)", cypher) and set(re.findall(r"\$(\w+)", cypher)) <= set(params)
    assert not re.search(r"\b(CREATE|MERGE|SET|DELETE|DETACH|DROP|CALL)\b", cypher, re.IGNORECASE)
    assert params["anchor_keys"] == ["inventory-service"]


def test_six_intents_yield_six_distinct_templates():
    queries = {compile(make_plan(intent))[0] for intent in ALL_INTENTS}
    assert len(queries) == 6


def test_compilation_is_deterministic():
    plan = make_plan(Intent.TIMELINE)
    assert compile(plan) == compile(plan)


def test_anchor_values_are_never_interpolated():
    hostile = "x' MATCH (n) DETACH DELETE n //"
    plan = make_plan(
        Intent.LOOKUP,
        anchors=[{"kind": "ANY", "text": hostile, "match": "hybrid"}],
    )

    cypher, params = compile(plan)

    assert hostile not in cypher
    assert params["anchor_keys"] == [hostile]


def test_caps_are_clamped_not_trusted():
    plan = make_plan(
        Intent.RELATIONSHIP,
        traverse={"max_hops": 99, "max_nodes": 5000},
        evidence={"max_spans_per_claim": 99},
    )

    _, params = compile(plan)

    assert params["max_hops"] == MAX_HOPS == 3
    assert params["max_nodes"] == MAX_NODES == 50
    assert params["max_spans"] <= 5


def test_time_defaults_to_valid_and_as_of_binds_as_a_parameter():
    cypher, params = compile(make_plan(Intent.LOOKUP))

    assert params["status_in"] == ["VALID"]
    assert params["as_of"] is None
    assert "c.valid_from <= $as_of" in cypher
    assert "c.valid_to > $as_of" in cypher


def test_superseded_chain_and_conflicts_widen_statuses():
    state_of = compile(make_plan(Intent.STATE_OF, time={"include_superseded_chain": True}))
    conflicts = compile(make_plan(Intent.CONFLICTS))

    assert "DEPRECATED" in state_of[1]["status_in"]
    assert conflicts[1]["status_in"] == ["DISPUTED"]


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "DROP", "anchors": [{"key": "x"}]},
        {"intent": "LOOKUP", "anchors": []},
        {"intent": "LOOKUP", "anchors": [{"key": "x"}], "traverse": {"max_hops": 0}},
        {"intent": "LOOKUP", "anchors": [{"key": "x"}], "time": {"status_in": ["SCHRODINGER"]}},
        {"intent": "LOOKUP", "anchors": [{"key": "x"}], "time": {"as_of": "not-a-date"}},
        {"intent": "LOOKUP", "anchors": [{"kind": "ANY"}]},
        {"intent": "LOOKUP", "anchors": [{"key": "x"}], "sql": "MATCH (n)"},
    ],
)
def test_invalid_plans_are_rejected_before_compilation(payload):
    with pytest.raises(ValidationError):
        validate_plan(payload)


def test_every_template_is_brace_balanced_and_returns_the_object():
    """Regression: an extra brace in the citation projection broke every query."""
    for intent in Intent:
        for anchor in ({"kind": "Service", "key": "inventory-service", "match": "exact"},):
            cqp = validate_plan({"intent": intent.value, "anchors": [anchor]})
            cypher, _ = compile(cqp)
            assert cypher.count("{") == cypher.count("}"), intent
            assert "c.object AS object" in cypher, intent
