# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The planner gate and the repair applied to model output. No model, no network."""

from __future__ import annotations

from retrieval import planner
from retrieval.planner import _names_an_identifier, _repair


def test_an_identifier_in_the_question_keeps_the_model_out() -> None:
    assert _names_an_identifier("Does inventory-service still use a Redis cache?")
    assert _names_an_identifier("is `/v1/accounts` still exposed?")
    assert _names_an_identifier("what replaced OWNERS_TABLE?")
    assert not _names_an_identifier("what is going on with the billing thing")


def test_repair_keeps_one_identity_per_anchor() -> None:
    plan = _repair(
        {
            "anchors": [
                {"kind": "ANY", "key": "billing", "text": "billing"},
                {"kind": "ANY", "key": "", "text": " invoices "},
                {"kind": "ANY", "key": "", "text": ""},
            ]
        }
    )

    assert plan["anchors"] == [
        {"kind": "ANY", "key": "billing", "text": None},
        {"kind": "ANY", "key": None, "text": "invoices"},
    ]


def test_repair_truncates_a_model_timestamp_and_never_invents_a_date() -> None:
    assert _repair({"time": {"as_of": "2022-01-01T00:00:00Z"}})["time"]["as_of"] == "2022-01-01"
    assert _repair({"time": {"as_of": "last spring"}})["time"]["as_of"] is None
    assert _repair({"time": {"as_of": None}})["time"]["as_of"] is None


def test_trace_says_the_model_never_ran_for_a_typed_question():
    """`source` is the answer to "parsed or understood", so it must never be a guess."""
    trace: dict[str, str] = {}

    planner.plan("Does inventory-service still use a Redis cache?", trace=trace)

    assert trace["source"] == "deterministic"
    assert "identifier" in trace["detail"]


def test_trace_says_the_model_ran_and_was_discarded(monkeypatch):
    trace: dict[str, str] = {}
    monkeypatch.setattr(
        planner,
        "_from_model",
        lambda _q: planner.CQP(intent=planner.Intent.LOOKUP, anchors=[planner.Anchor(key="x")]),
    )

    planner.plan("how do the parts fit together", trace=trace)

    assert trace["source"] == "deterministic"
    assert "no typed anchor" in trace["detail"]


def test_trace_says_the_model_typed_the_anchors(monkeypatch):
    trace: dict[str, str] = {}
    monkeypatch.setattr(
        planner,
        "_from_model",
        lambda _q: planner.CQP(
            intent=planner.Intent.LOOKUP,
            anchors=[planner.Anchor(kind="Table", key="users", match="exact")],
        ),
    )

    planner.plan("how do the parts fit together", trace=trace)

    assert trace["source"] == "model"


def test_trace_reports_a_failed_model_call(monkeypatch):
    trace: dict[str, str] = {}
    monkeypatch.setattr(planner, "_from_model", lambda _q: (_ for _ in ()).throw(OSError("no model")))

    planner.plan("how do the parts fit together", trace=trace)

    assert trace["source"] == "deterministic"
    assert "model call failed" in trace["detail"]
