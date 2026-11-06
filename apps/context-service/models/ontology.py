# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Closed enums from docs/03-ontology.md and docs/04-temporal-model.md."""

from enum import StrEnum


class EntityKind(StrEnum):
    SERVICE = "Service"
    APPLICATION = "Application"
    PACKAGE = "Package"
    REPOSITORY = "Repository"
    ENVIRONMENT = "Environment"
    CONCEPT = "Concept"
    TERM = "Term"
    DECISION = "Decision"
    POLICY = "Policy"
    CONVENTION = "Convention"
    DATASTORE = "Datastore"
    LIBRARY = "Library"
    ENDPOINT = "Endpoint"
    PORT = "Port"
    ENV_VAR = "EnvVar"
    RISK = "Risk"
    VULNERABILITY = "Vulnerability"
    INCIDENT = "Incident"
    ISSUE = "Issue"
    TEAM = "Team"
    PERSON = "Person"
    RELEASE = "Release"
    MEETING = "Meeting"
    DIAGRAM = "Diagram"
    SCHEMA = "Schema"
    TABLE = "Table"
    COLUMN = "Column"


class Predicate(StrEnum):
    """Extractable relationships. The trust family (CONTRADICTS, CORROBORATES, …) is
    produced by the resolver, never extracted, so it is not in this enum."""

    CALLS = "CALLS"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    EXPOSES = "EXPOSES"
    LISTENS_ON = "LISTENS_ON"
    AUTHENTICATES_VIA = "AUTHENTICATES_VIA"
    DEPENDS_ON = "DEPENDS_ON"
    IMPORTS = "IMPORTS"
    BUILDS_FROM = "BUILDS_FROM"
    DEPLOYED_BY = "DEPLOYED_BY"
    MEMBER_OF_WORKSPACE = "MEMBER_OF_WORKSPACE"
    DEFINES_TABLE = "DEFINES_TABLE"
    HAS_COLUMN = "HAS_COLUMN"
    MIGRATES = "MIGRATES"
    SHARES_SCHEMA_WITH = "SHARES_SCHEMA_WITH"
    OWNS = "OWNS"
    DECIDED_BY = "DECIDED_BY"
    SUPERSEDES = "SUPERSEDES"
    IMPLEMENTS = "IMPLEMENTS"
    VIOLATES = "VIOLATES"
    PROHIBITS = "PROHIBITS"
    MENTIONS = "MENTIONS"
    CAUSED_BY = "CAUSED_BY"
    RESOLVED_BY = "RESOLVED_BY"
    PLANNED_IN = "PLANNED_IN"
    DISCUSSED_IN = "DISCUSSED_IN"


class Polarity(StrEnum):
    ASSERTS = "ASSERTS"
    NEGATES = "NEGATES"


class Modality(StrEnum):
    FACT = "FACT"
    DECISION = "DECISION"
    PROPOSAL = "PROPOSAL"
    PLAN = "PLAN"
    HYPOTHESIS = "HYPOTHESIS"
    PROHIBITION = "PROHIBITION"


class Status(StrEnum):
    VALID = "VALID"
    DEPRECATED = "DEPRECATED"
    PLANNED = "PLANNED"
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


class SourceType(StrEnum):
    """What kind of artefact a file is. Decides the authority prior (settings.py)."""

    MIGRATION = "MIGRATION"
    CONFIG = "CONFIG"
    CODE = "CODE"
    API_SPEC = "API_SPEC"
    ADR = "ADR"
    RELEASE = "RELEASE"
    DESIGN_DOC = "DESIGN_DOC"
    ISSUE = "ISSUE"
    MEETING = "MEETING"
    WIKI = "WIKI"
    DIAGRAM = "DIAGRAM"
    HISTORICAL = "HISTORICAL"
    OTHER = "OTHER"


class TimeSignal(StrEnum):
    """How a date was obtained — rows of the table in docs/04-temporal-model.md."""

    EXPLICIT_FIELD = "EXPLICIT_FIELD"
    FILENAME = "FILENAME"
    BYLINE = "BYLINE"
    REFERENCED_RECORD = "REFERENCED_RECORD"
    DIAGRAM_TITLE = "DIAGRAM_TITLE"
    GIT = "GIT"


class Precision(StrEnum):
    DAY = "day"
    MONTH = "month"


class Verdict(StrEnum):
    """The answer-level split an agent acts on. Distinct from Status: a VALID claim
    with too little evidence still gets NOT_VALID."""

    VALID = "VALID"
    NOT_VALID = "NOT_VALID"
