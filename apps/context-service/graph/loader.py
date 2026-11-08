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
    cl.object = c.object,
    cl.polarity = c.polarity,
    cl.modality = c.modality,
    cl.status = c.status,
    cl.score = c.score,
    cl.confidence = c.confidence,
    cl.valid_from = c.valid_from,
    cl.valid_to = c.valid_to,
    cl.observed_at = c.observed_at,
    cl.extractor = c.extractor,
    cl.extractor_version = c.extractor_version,
    cl.source_type = c.source_type,
    cl.authority = c.authority
WITH cl, c
MERGE (s:Entity {key: c.subject})
SET s.kind = coalesce(s.kind, c.subject_kind)
MERGE (cl)-[:ABOUT]->(s)
FOREACH (sp IN c.spans |
  MERGE (src:Source {path: sp.path})
  SET src.content_hash = sp.content_hash
  MERGE (span:Span {path: sp.path, start_line: sp.start_line, end_line: sp.end_line})
  MERGE (span)-[:IN]->(src)
  MERGE (cl)-[:EVIDENCED_BY]->(span)
)
FOREACH (r IN c.regions |
  MERGE (rsrc:Source {path: r.path})
  SET rsrc.content_hash = coalesce(rsrc.content_hash, r.content_hash)
  MERGE (rspan:Span {path: r.path, start_line: 1, end_line: 1,
                     region_x: r.region_x, region_y: r.region_y,
                     region_w: r.region_w, region_h: r.region_h})
  MERGE (rspan)-[:IN]->(rsrc)
  MERGE (cl)-[:EVIDENCED_BY]->(rspan)
)
"""

# A region merge cannot be folded into the line merge: Cypher aborts the whole UNWIND
# when a merge key is null, and every line span has no region (measured on the live store).
# Both span kinds therefore run through FOREACH with a fixed key each, and a claim that has
# only a region survives — an UNWIND over an empty list would drop it.
DELETE_VERSION = """
MATCH (cl:Claim {extractor: $extractor}) WHERE cl.extractor_version <> $version
DETACH DELETE cl
"""

SWEEP_SPANS = """
MATCH (s:Span) WHERE NOT (s)<-[:EVIDENCED_BY]-() DETACH DELETE s
"""


def assert_loadable(claims: list[ClaimRecord]) -> None:
    """The non-null guarantee the Enterprise constraints would have given us."""
    for claim in claims:
        if claim.observed_at is None or not claim.evidence:
            raise ValueError(f"claim {claim.claim_id} has no observed_at or no evidence")


def load(driver: Driver, claims: list[ClaimRecord], *, replace: bool = False) -> int:
    """Upsert claims; with `replace`, an extractor's other versions are dropped first.

    A version bump changes `claim_id`, so without the delete the old rows survive beside the
    new ones as if both were true (ADR-0012). "Replace" means *this extractor, this version*:
    only extractors present in the batch are touched, so loading one file cannot empty another.
    """
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
            "subject_kind": r.claim.subject.kind,
            "object": r.claim.object.key if hasattr(r.claim.object, "key") else str(r.claim.object),
            "extractor": r.claim.extractor,
            "extractor_version": r.claim.extractor_version,
            "source_type": str(r.claim.source_type),
            "authority": r.claim.authority,
            "spans": [s.model_dump(exclude={"region"}) for s in r.claim.evidence if s.region is None],
            "regions": [
                {
                    "path": span.path,
                    "content_hash": span.content_hash,
                    "region_x": span.region.x,
                    "region_y": span.region.y,
                    "region_w": span.region.w,
                    "region_h": span.region.h,
                }
                for span in r.claim.evidence
                if span.region is not None
            ],
        }
        for claim_id, r in resolved.items()
    ]
    versions = sorted({(row["extractor"], row["extractor_version"]) for row in rows})
    with driver.session() as session:
        session.run("RETURN 1")
        if replace:
            for extractor, version in versions:
                session.run(DELETE_VERSION, extractor=extractor, version=version).consume()
        rows and session.run(UPSERT_CLAIM, claims=rows).consume()
        if replace:
            session.run(SWEEP_SPANS).consume()
    return len(rows)


def apply_schema(driver: Driver) -> None:
    with driver.session() as session:
        # `//` comments are stripped first: schema.cypher documents why a key exists, and a
        # comment is not a statement.
        body = "\n".join(line for line in SCHEMA.splitlines() if not line.strip().startswith("//"))
        for statement in filter(None, (s.strip() for s in body.split(";"))):
            session.run(statement).consume()


def connect(uri: str, user: str, password: str) -> Driver:
    return GraphDatabase.driver(uri, auth=(user, password))
