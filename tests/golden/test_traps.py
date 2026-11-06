# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The trap catalogue (docs/01-corpus-survey.md). Each case asserts three things
separately: the answer, the status labels, and the citations."""

from datetime import date

import pytest

from models.answer import Answer, EvidenceFilter, Statement, TimeFilter
from models.claim import ClaimRecord
from models.ontology import Status, Verdict
from service import query
from settings import Settings
from tests.conftest import REPO, TODAY

CORPUS = "vendor/att-hackathon-task"


def _ask(cfg: Settings, question: str, as_of: date = TODAY) -> Answer:
    return query(question, cfg, TimeFilter(as_of=as_of), EvidenceFilter())


def _one(statements: list[Statement], text: str) -> Statement:
    hits = [s for s in statements if s.text == text]
    assert len(hits) == 1, [s.text for s in statements]
    return hits[0]


def _cited(st: Statement) -> set[str]:
    return {f"{c.path}:{c.lines[0]}" for c in st.citations}


def _all_citations_exist(answer: Answer) -> None:
    for st in answer.claims + answer.not_valid:
        for c in st.citations:
            assert (REPO / c.path).is_file(), c.path
            assert len(c.hash) == 64


def test_t1_removed_cache_is_deprecated_not_current(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    a = _ask(cfg, "does inventory still use redis?")

    valid_no = _one(a.claims, "inventory-service NOT READS_FROM redis")
    stale = _one(a.not_valid, "inventory-service READS_FROM redis")
    assert "redis" not in {s.object.key for s in a.claims if s.polarity == "ASSERTS"}

    assert (valid_no.status, valid_no.verdict) == (Status.VALID, Verdict.VALID)
    assert (stale.status, stale.verdict) == (Status.DEPRECATED, Verdict.NOT_VALID)
    assert stale.valid_to == date(2026, 6, 4)

    assert f"{CORPUS}/docs/adr/003-stock-cache.md:6" in _cited(valid_no)
    assert f"{CORPUS}/wiki/inventory-service.md:5" in _cited(stale)
    assert f"{CORPUS}/docs/adr/003-stock-cache.md:6" in {
        f"{c.path}:{c.lines[0]}" for c in stale.superseded_by
    }
    _all_citations_exist(a)


def test_t1_point_in_time_before_removal(cfg: Settings, records: list[ClaimRecord]) -> None:
    a = _ask(cfg, "does inventory still use redis?", as_of=date(2026, 3, 1))
    past = _one(a.claims, "inventory-service READS_FROM redis")
    assert past.status is Status.VALID
    assert f"{CORPUS}/wiki/inventory-service.md:5" in _cited(past)


def test_t2_schema_drift_column_renamed(cfg: Settings, records: list[ClaimRecord]) -> None:
    a = _ask(cfg, "does the users table have a status column?")

    renamed = _one(a.claims, "user-service.users NOT HAS_COLUMN status")
    current = _one(a.claims, "user-service.users HAS_COLUMN account_status")
    stale = _one(a.not_valid, "user-service.users HAS_COLUMN status")

    assert renamed.verdict is current.verdict is Verdict.VALID
    assert stale.status is Status.DEPRECATED

    migration = f"{CORPUS}/apps/user-service/migrations/002-account-tiers.sql:1"
    assert migration in _cited(renamed) and migration in _cited(current)
    assert f"{CORPUS}/wiki/accounts-http.md:5" in _cited(stale)
    _all_citations_exist(a)


def test_t2_tiers_proposal_is_stale(cfg: Settings, records: list[ClaimRecord]) -> None:
    a = _ask(cfg, "is customer_tier still only a proposal?")
    shipped = next(s for s in a.claims if s.text == "user-service.users HAS_COLUMN customer_tier")
    stale = next(s for s in a.not_valid if s.text == "user-service.users HAS_COLUMN customer_tier")
    assert shipped.status is Status.VALID
    assert stale.status is Status.DEPRECATED and "realised" in stale.reason
    assert f"{CORPUS}/wiki/accounts-http.md:7" in _cited(stale)


def test_t3_history_contract_is_deprecated_by_path(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    a = _ask(cfg, "what does accounts v1 GET /v1/users return, status?")
    stale = _one(a.not_valid, "user-service.users HAS_COLUMN status")
    history = f"{CORPUS}/api-specs/history/accounts-v1.md:5"
    assert history in _cited(stale)
    assert stale.status is Status.DEPRECATED
    assert all(history not in _cited(s) for s in a.claims)


def test_target_state_diagram_is_not_proof_the_ticket_is_done(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    """issues/EDGE-53.md:7 — "A diagram showing the target topology should not be used
    as proof that this ticket is done." Deferred ticket + drawing ≠ current fact."""
    a = _ask(cfg, "does the operations console write stock through the api gateway?")
    target = [s for s in a.not_valid if s.text == "operations-console CALLS api-gateway"]
    current = _one(a.claims, "operations-console CALLS inventory-service")

    assert {s.status for s in target} == {Status.PLANNED, Status.DISPUTED}
    assert all(s.verdict is Verdict.NOT_VALID for s in target)
    assert current.status is Status.VALID

    cited = set().union(*(_cited(s) for s in target))
    assert f"{CORPUS}/issues/EDGE-53.md:1" in cited
    assert f"{CORPUS}/diagrams/architecture-september.png:4" in cited
    assert f"{CORPUS}/docs/adr/005-support-access.md:6" in _cited(current)


@pytest.mark.skip(reason="T4: entity resolution (no merge on shared email) is not implemented")
def test_t4_shared_email_is_not_a_join_key() -> None: ...


@pytest.mark.skip(reason="T5: workspace scoping of archive/ name collisions is not implemented")
def test_t5_archive_name_collisions() -> None: ...


def test_t6_proposal_is_not_a_decision(cfg: Settings, records: list[ClaimRecord]) -> None:
    a = _ask(cfg, "is people SSO approved?")
    proposal = _one(a.not_valid, "people-identity-bridge DECIDED_BY ADR-004")
    prohibition = _one(a.claims, "people-identity-bridge PROHIBITS approved-sso-rollout")

    assert proposal.status is Status.PROPOSED and proposal.verdict is Verdict.NOT_VALID
    assert "blocked by prohibition" in proposal.reason
    assert prohibition.verdict is Verdict.VALID
    assert f"{CORPUS}/docs/adr/004-people-sso.md:6" in _cited(proposal)


def test_t7_security_hypothesis_stays_disputed(cfg: Settings, records: list[ClaimRecord]) -> None:
    a = _ask(cfg, "is the order lookup secure?")
    risk = _one(a.not_valid, "order-service VIOLATES order-detail-ownership-check")

    assert a.claims == [] and a.gaps
    assert risk.status is Status.DISPUTED
    assert f"{CORPUS}/issues/SEC-22.md:5" in _cited(risk)
