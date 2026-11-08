"""The compiler is pure: six templates, parameters only, caps clamped, nothing writable."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from retrieval.cqp import CQP, MAX_NODES, Intent, Traverse, compile, validate_plan

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
        traverse={"max_nodes": 5000},
        evidence={"max_spans_per_claim": 99},
    )

    _, params = compile(plan)

    assert params["max_nodes"] == MAX_NODES == 50
    assert params["max_spans"] <= 5


def test_no_hop_cap_is_claimed_or_bound():
    """#75: `max_hops` was bound into params and no template ever used it, while a comment
    promised a hard cap of 3. The templates are single-hop stars, so the field is gone and
    nothing may claim a hop budget it does not enforce."""
    for intent in Intent:
        cypher, params = compile(make_plan(intent))

        assert "max_hops" not in params, intent
        assert "max_hops" not in cypher, intent
    assert "max_hops" not in Traverse.model_fields


def test_time_defaults_to_valid_and_as_of_binds_as_a_parameter():
    cypher, params = compile(make_plan(Intent.LOOKUP))

    assert params["status_in"] == ["VALID"]
    assert params["as_of"] is None
    assert "c.valid_from <= $as_of" in cypher
    assert "c.valid_to > $as_of" in cypher


def test_anchor_matches_the_object_not_only_the_entity():
    """`Which service listens on port 5005?` returned nothing: 5005 is a claim object,
    never an entity key, so identifier and port lookups were unreachable. RISKS carried
    its own copy of the match and kept the old one, hence the loop over every intent."""
    for intent in Intent:
        cypher, _ = compile(make_plan(intent))

        assert "toLower(c.object) CONTAINS toLower($anchor_keys[i])" in cypher, intent
        assert "toLower(e.key) CONTAINS toLower($anchor_keys[i])" in cypher, intent
        # An anchor that names a kind must not match an entity of another kind.
        assert "$anchor_kinds[i]" in cypher, intent


def test_superseded_chain_and_conflicts_widen_statuses():
    state_of = compile(make_plan(Intent.STATE_OF, time={"include_superseded_chain": True}))
    conflicts = compile(make_plan(Intent.CONFLICTS))

    assert "DEPRECATED" in state_of[1]["status_in"]
    assert conflicts[1]["status_in"] == ["DISPUTED"]


def test_timeline_supersession_joins_the_same_subject():
    """#72: the successor was matched on the predicate alone, so two entities that share
    one predicate (every service READS_FROM something) superseded each other across
    subjects. `later` must hang off the anchored entity `e`, not a fresh `(:Entity)`."""
    cypher, params = compile(make_plan(Intent.TIMELINE))

    assert "OPTIONAL MATCH (later:Claim)-[:ABOUT]->(e)" in cypher
    assert "-[:ABOUT]->(:Entity)" not in cypher
    assert "later.predicate = c.predicate" in cypher
    assert "superseded_by" in cypher
    assert "max_nodes" in params


def test_timeline_tie_break_matches_the_python_rule():
    """#80: the Cypher picked the lowest id among *every* later claim. It must pick the
    earliest `valid_from` first and break ties on the lowest id, like `_link_superseded`."""
    cypher, _ = compile(make_plan(Intent.TIMELINE))

    assert "x.valid_from < m" in cypher, "earliest valid_from must win"
    assert "x.id < m" in cypher, "ties must break on the lowest claim id"


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "DROP", "anchors": [{"key": "x"}]},
        {"intent": "LOOKUP", "anchors": []},
        {"intent": "LOOKUP", "anchors": [{"key": "x"}], "traverse": {"max_nodes": 0}},
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
