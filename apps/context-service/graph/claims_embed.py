"""Every claim as a vector: the graph searchable by meaning, not only by key.

`cli index` embeds each claim's statement ("inventory-service VIOLATES POST /v1/availability")
so a question that names nothing the extractor recognised can still reach real claims with
their statuses, dates and citations. The text embeds the *assertion*, never the excerpt:
retrieved corpus prose must not become the thing similarity operates on.
"""

from __future__ import annotations

from collections.abc import Callable

from neo4j import Driver

CLAIMS = """
MATCH (c:Claim)-[:ABOUT]->(e:Entity)
RETURN c.id AS id, e.key AS subject, c.predicate AS predicate, c.object AS object,
       c.polarity AS polarity
"""

UPSERT = """
UNWIND $claims AS row
MATCH (c:Claim {id: row.id})
SET c.embedding = row.embedding
RETURN count(c) AS matched
"""

BATCH = 64


def statement(row: dict) -> str:
    """The same text `_statement` renders for a user: subject, polarity, predicate, object."""
    negated = str(row.get("polarity") or "ASSERTS").upper() == "NEGATES"
    parts = [str(row.get("subject") or "unknown"), "NOT" if negated else "", str(row.get("predicate") or "")]
    if row.get("object") is not None and str(row["object"]):
        parts.append(str(row["object"]))
    return " ".join(part for part in parts if part)


def build(driver: Driver, embed: Callable[[str], list[float] | None]) -> dict[str, int]:
    """(Re)embed every claim. Idempotent: a re-run overwrites, never appends.

    `offered` is what we tried to write; `matched` is what the graph accepted. Reporting
    only the first is how an index run claimed 311 vectors while the graph held none.
    """
    rows = [dict(record) for record in driver.execute_query(CLAIMS).records]
    payload: list[dict] = []
    offered = 0
    matched = 0
    for row in rows:
        vector = embed(statement(row))
        if not vector:
            continue
        payload.append({"id": row["id"], "embedding": vector})
        if len(payload) >= BATCH:
            offered += len(payload)
            matched += _write(driver, payload)
            payload = []
    if payload:
        offered += len(payload)
        matched += _write(driver, payload)
    return {"offered": offered, "matched": matched}


def _write(driver: Driver, payload: list[dict]) -> int:
    rows = driver.execute_query(UPSERT, claims=payload).records
    return int(rows[0]["matched"]) if rows else 0
