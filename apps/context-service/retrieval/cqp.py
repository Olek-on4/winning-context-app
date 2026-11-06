"""The Context Query Plan: the only door into Cypher.

The planner fills this schema; the compiler emits one of six fixed, parameterised,
read-only templates. User strings never reach the query text, only the parameter map.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from graph.resolver import Status

MAX_HOPS = 3
MAX_NODES = 50
MAX_SPANS = 5

_STATUS_VALUES = {status.value for status in Status}


class Intent(StrEnum):
    """Closed set. Each value maps to exactly one compiler template."""

    LOOKUP = "LOOKUP"
    STATE_OF = "STATE_OF"
    RELATIONSHIP = "RELATIONSHIP"
    CONFLICTS = "CONFLICTS"
    TIMELINE = "TIMELINE"
    RISKS = "RISKS"


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: str = Field(default="ANY", min_length=1)
    key: str | None = None
    text: str | None = None
    match: Literal["exact", "hybrid"] | None = None

    @model_validator(mode="after")
    def _one_pointer(self) -> "Anchor":
        if self.key == "":
            self.key = None
        if self.text == "":
            self.text = None
        if (self.key is None) == (self.text is None):
            raise ValueError("anchor needs exactly one of key or text")
        if self.match is None:
            self.match = "exact" if self.key is not None else "hybrid"
        return self


class Traverse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    predicates: list[str] = Field(default_factory=list)
    direction: Literal["OUT", "IN", "BOTH"] = "BOTH"
    max_hops: int = Field(default=1, ge=1)
    max_nodes: int = Field(default=MAX_NODES, ge=1)


class TimeFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    as_of: str | None = None
    status_in: list[str] = Field(default_factory=lambda: [Status.VALID.value], min_length=1)
    include_superseded_chain: bool = False

    @field_validator("as_of")
    @classmethod
    def _normalise_as_of(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or value.lower() in {"now", "current"}:
            return None
        date.fromisoformat(value)  # ValueError is the rejection
        return value

    @field_validator("status_in")
    @classmethod
    def _known_statuses(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            status = item.strip().upper()
            if status not in _STATUS_VALUES:
                raise ValueError(f"unknown status {item!r}")
            if status not in out:
                out.append(status)
        if not out:
            raise ValueError("status_in needs at least one status")
        return out


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    require_citations: bool = True
    max_spans_per_claim: int = Field(default=2, ge=1)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_budget: int = Field(default=2000, ge=1)
    include_conflicts: bool = True


class CQP(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cqp_version: Literal["1.0"] = "1.0"
    intent: Intent
    anchors: list[Anchor] = Field(min_length=1)
    traverse: Traverse = Field(default_factory=Traverse)
    time: TimeFilter = Field(default_factory=TimeFilter)
    evidence: Evidence = Field(default_factory=Evidence)
    output: Output = Field(default_factory=Output)


def validate_plan(plan: dict) -> CQP:
    """Raise ValidationError for anything the compiler would not execute as written."""
    return CQP.model_validate(plan)


# --- Templates -------------------------------------------------------------
# Labels, relationship types and constants are literals; every user value is a $param.
# ABOUT only ever points Claim -> Entity in this schema, so direction is a plan field
# without a template branch; max_hops binds as a cap even when the star shape needs one.

_FILTER = """MATCH (c:Claim)-[:ABOUT]->(e:Entity)
WHERE any(a IN $anchor_keys WHERE toLower(e.key) CONTAINS toLower(a))
  AND c.status IN $status_in
  AND c.confidence >= $min_confidence
  AND ($as_of IS NULL OR ((c.valid_from IS NULL OR c.valid_from <= $as_of)
       AND (c.valid_to IS NULL OR c.valid_to > $as_of)))"""

_PREDICATES = "\n  AND (size($predicates) = 0 OR c.predicate IN $predicates)"


def _citations(head: str) -> str:
    return (
        "OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(sp:Span)-[:IN]->(src:Source)\n"
        f"WITH {head}[x IN collect(DISTINCT {{path: src.path, start_line: sp.start_line, "
        "end_line: sp.end_line, hash: src.content_hash}) "
        "WHERE x.path IS NOT NULL][0..$max_spans] AS citations"
    )


def _return_clause(extra: str = "") -> str:
    tail = ",\n       " + extra + ",\n       citations" if extra else ",\n       citations"
    return (
        "RETURN c.id AS id, e.key AS subject, c.predicate AS predicate, c.object AS object,\n"
        "       c.polarity AS polarity, c.modality AS modality, c.status AS status,\n"
        "       c.confidence AS confidence, c.valid_from AS valid_from,\n"
        "       c.valid_to AS valid_to, c.observed_at AS observed_at"
        + tail
    )


_TEMPLATES: dict[Intent, str] = {
    Intent.LOOKUP: (
        _FILTER
        + "\n"
        + _citations("c, e, ")
        + "\n"
        + _return_clause()
        + "\nORDER BY c.score DESC, c.id ASC\nLIMIT $max_nodes"
    ),
    Intent.STATE_OF: (
        _FILTER
        + _PREDICATES
        + "\n"
        + _citations("c, e, ")
        + "\n"
        + _return_clause()
        + "\nORDER BY c.valid_from DESC, c.id ASC\nLIMIT $max_nodes"
    ),
    Intent.RELATIONSHIP: (
        _FILTER
        + _PREDICATES
        + "\n"
        + _citations("c, e, ")
        + "\n"
        + _return_clause("c.predicate AS via")
        + "\nORDER BY c.predicate ASC, c.score DESC, c.id ASC\nLIMIT $max_nodes"
    ),
    Intent.CONFLICTS: (
        _FILTER
        + _PREDICATES
        + "\n"
        + _citations("c, e, ")
        + "\n"
        + _return_clause("c.polarity AS side")
        + "\nORDER BY c.predicate ASC, c.polarity ASC, c.id ASC\nLIMIT $max_nodes"
    ),
    Intent.TIMELINE: (
        _FILTER
        + _PREDICATES
        + """
OPTIONAL MATCH (later:Claim)-[:ABOUT]->(:Entity)
WHERE later.predicate = c.predicate AND later.status = 'VALID'
  AND later.valid_from > c.valid_from
WITH c, e, collect(DISTINCT later.id) AS later_ids
WITH c, e, reduce(m = '', x IN later_ids | CASE WHEN m = '' OR x < m THEN x ELSE m END) AS superseded
"""
        + _citations("c, e, superseded, ")
        + "\n"
        + _return_clause("CASE WHEN superseded = '' THEN null ELSE superseded END AS superseded_by")
        + "\nORDER BY c.valid_from ASC, c.id ASC\nLIMIT $max_nodes"
    ),
    Intent.RISKS: (
        """MATCH (c:Claim)-[:ABOUT]->(e:Entity)
WHERE (any(a IN $anchor_keys WHERE toLower(e.key) CONTAINS toLower(a)) OR c.predicate IN $risk_predicates)
  AND c.status IN $status_in
  AND c.confidence >= $min_confidence
  AND ($as_of IS NULL OR ((c.valid_from IS NULL OR c.valid_from <= $as_of)
       AND (c.valid_to IS NULL OR c.valid_to > $as_of)))
WITH c, e, CASE WHEN any(a IN $anchor_keys WHERE toLower(e.key) CONTAINS toLower(a)) THEN 1 ELSE 0 END AS anchored
"""
        + _citations("c, e, anchored, ")
        + "\n"
        + _return_clause("anchored AS anchored")
        + "\nORDER BY anchored DESC, c.score DESC, c.id ASC\nLIMIT $max_nodes"
    ),
}

_WRITE_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|CALL|FOREACH|LOAD\s+CSV)\b", re.IGNORECASE
)


def compile(plan: CQP) -> tuple[str, dict]:
    """Pure: the same plan always yields the same query and the same parameters."""
    template = _TEMPLATES[plan.intent]

    statuses = list(plan.time.status_in)
    if plan.intent is Intent.CONFLICTS:
        # The intent is defined by the disputed set; other statuses are history queries.
        statuses = [Status.DISPUTED.value]
    elif plan.time.include_superseded_chain and Status.DEPRECATED.value not in statuses:
        statuses.append(Status.DEPRECATED.value)

    params: dict = {
        "anchor_keys": [anchor.key or anchor.text or "" for anchor in plan.anchors],
        "predicates": list(plan.traverse.predicates),
        "status_in": statuses,
        "as_of": plan.time.as_of,
        "min_confidence": float(plan.evidence.min_confidence),
        "max_spans": min(max(plan.evidence.max_spans_per_claim, 1), MAX_SPANS),
        "max_nodes": min(max(plan.traverse.max_nodes, 1), MAX_NODES),
        "max_hops": min(max(plan.traverse.max_hops, 1), MAX_HOPS),
    }
    if plan.intent is Intent.RISKS:
        params["risk_predicates"] = ["VIOLATES", "PROHIBITS"]

    if _WRITE_CLAUSE.search(template):
        raise ValueError(f"template for {plan.intent} is not read-only")

    return template, params
