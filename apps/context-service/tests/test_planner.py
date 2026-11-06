# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The planner gate and the repair applied to model output. No model, no network."""

from __future__ import annotations

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
