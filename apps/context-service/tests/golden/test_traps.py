"""The seven corpus traps, asserted end to end against a real graph.

Each case checks three things: the answer, the status labels, and the citation. A right
answer with the wrong citation is a lucky guess. Skipped when Neo4j is not running.

    docker compose -f infra/neo4j/compose.yaml up -d
    cd apps/context-service && uv run pytest tests/golden -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]
CORPUS = REPO / "vendor" / "att-hackathon-task"
FIXTURES = REPO / "data" / "fixtures" / "claims-sample.jsonl"


@pytest.fixture(scope="module")
def service():
    from graph.loader import apply_schema, connect, load
    from models.claim import ClaimRecord
    from retrieval.service import ContextService

    try:
        driver = connect("bolt://localhost:7687", "neo4j", "northstar")
        driver.verify_connectivity()
    except Exception:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip("Neo4j not reachable")

    claims = [ClaimRecord.model_validate_json(line) for line in FIXTURES.read_text().splitlines() if line.strip()]
    apply_schema(driver)
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
    load(driver, claims)
    yield ContextService(driver, CORPUS)
    driver.close()


def ask(service, question: str, **kw) -> dict:
    return service.answer(question, **kw)


def statuses(result: dict) -> dict[str, str]:
    return {claim["statement"]: claim["status"] for claim in result["claims"]}


def cited_paths(result: dict) -> set[str]:
    return {c["path"] for claim in result["claims"] for c in claim["citations"]}


def test_g1_removed_cache_is_deprecated_not_absent(service):
    result = ask(service, "Does inventory-service still use a Redis cache?")
    table = statuses(result)

    assert any(s == "VALID" and "sqlite" in name for name, s in table.items())
    assert any(s == "VALID" and "NOT" in name and "redis" in name for name, s in table.items())
    assert any(s == "DEPRECATED" and "redis" in name for name, s in table.items())
    assert {"docs/adr/003-stock-cache.md", "releases/2026-06-v1.3.md"} <= cited_paths(result)


def test_g2_renamed_column_is_not_reported_as_current(service):
    result = ask(service, "What fields does the users table have?")
    table = statuses(result)

    assert any(s == "VALID" and "account_status" in name for name, s in table.items())
    # The negation row is VALID; what must not be VALID is a bare "HAS_COLUMN status".
    assert all(
        s != "VALID"
        for name, s in table.items()
        if name.endswith("status") and "account" not in name and " NOT " not in name
    )
    assert "apps/user-service/migrations/002-account-tiers.sql" in cited_paths(result)


def test_g3_superseded_contract_is_deprecated(service):
    result = ask(service, "What endpoints does the accounts service expose?")
    table = statuses(result)

    assert any(s == "DEPRECATED" and "/v1/accounts" in name for name, s in table.items())
    assert "api-specs/history/accounts-v1.md" in cited_paths(result)


def test_g4_shared_email_is_not_a_join(service):
    result = ask(service, "How do people and accounts connect?")
    table = statuses(result)

    assert any("SIMILAR_NAME_TO" in name and s == "DISPUTED" for name, s in table.items())
    assert not any("SAME_AS" in name or "IDENTICAL" in name for name in table)
    assert "docs/design/people-account-link.md" in cited_paths(result)


def test_g5_archive_payment_service_is_not_the_payment_flow(service):
    result = ask(service, "Is the PaymentService in the payment flow?")
    table = statuses(result)

    assert any("archive/conference-registration.PaymentService" in name for name in table)
    assert "archive/conference-registration/README.md" in cited_paths(result)


def test_g6_sso_is_proposed_never_valid(service):
    result = ask(service, "Do we have SSO between People and Accounts?")
    table = statuses(result)

    sso = {name: s for name, s in table.items() if "sso" in name.lower()}
    assert any(s == "PROPOSED" for s in sso.values())
    # The release says SSO is *not* implemented; that negation being VALID is the point.
    assert all(s != "VALID" for name, s in sso.items() if " NOT " not in name)
    assert "docs/adr/004-people-sso.md" in cited_paths(result)


def test_g7_security_concern_stays_disputed(service):
    result = ask(service, "What are the risks in the payments service?")
    table = statuses(result)

    assert any(s == "DISPUTED" for name, s in table.items() if "VIOLATES" in name)
    assert "incidents/2026-08-19-payment-retry.md" in cited_paths(result)
