"""Load resolved claims into Neo4j. Idempotent by construction: claim ids are content-derived.

Only pointers are stored (path, lines, hash) — never the excerpt. The text is read back
from the corpus at query time, so the graph can never disagree with the repository.
"""

from __future__ import annotations

from pathlib import Path

from neo4j import Driver, GraphDatabase

from graph.resolver import Resolved, resolve
from models.claim import ClaimRecord

SCHEMA = Path(__file__).with_name("schema.cypher").read_text()

UPSERT_CLAIM = """
UNWIND $claims AS c
MERGE (cl:Claim {id: c.id})
SET cl.predicate = c.predicate,
    cl.polarity = c.polarity,
    cl.modality = c.modality,
    cl.status = c.status,
    cl.score = c.score,
    cl.confidence = c.confidence,
    cl.valid_from = c.valid_from,
    cl.valid_to = c.valid_to,
    cl.observed_at = c.observed_at
WITH cl, c
MERGE (s:Entity {key: c.subject})
MERGE (cl)-[:ABOUT]->(s)
WITH cl, c
UNWIND c.spans AS sp
MERGE (src:Source {path: sp.path})
SET src.content_hash = sp.content_hash
MERGE (span:Span {path: sp.path, start_line: sp.start_line, end_line: sp.end_line})
MERGE (span)-[:IN]->(src)
MERGE (cl)-[:EVIDENCED_BY]->(span)
"""


def assert_loadable(claims: list[ClaimRecord]) -> None:
    """The non-null guarantee the Enterprise constraints would have given us."""
    for claim in claims:
        if claim.observed_at is None or not claim.evidence:
            raise ValueError(f"claim {claim.claim_id} has no observed_at or no evidence")


def load(driver: Driver, claims: list[ClaimRecord]) -> int:
    assert_loadable(claims)
    resolved: dict[str, Resolved] = resolve(claims)
    rows = [
        {
            "id": claim_id,
            "predicate": r.claim.predicate,
            "polarity": r.claim.polarity.value,
            "modality": r.claim.modality.value,
            "status": r.status.value,
            "score": r.score,
            "confidence": r.confidence or r.claim.confidence,
            "valid_from": r.claim.valid_from.isoformat() if r.claim.valid_from else None,
            "valid_to": r.valid_to.isoformat() if r.valid_to else None,
            "observed_at": r.claim.observed_at.isoformat() if r.claim.observed_at else None,
            "subject": r.claim.subject.key,
            "spans": [s.model_dump() for s in r.claim.evidence],
        }
        for claim_id, r in resolved.items()
    ]
    with driver.session() as session:
        session.run("RETURN 1")
        rows and session.run(UPSERT_CLAIM, claims=rows).consume()
    return len(rows)


def apply_schema(driver: Driver) -> None:
    with driver.session() as session:
        for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            session.run(statement).consume()


def connect(uri: str, user: str, password: str) -> Driver:
    return GraphDatabase.driver(uri, auth=(user, password))
