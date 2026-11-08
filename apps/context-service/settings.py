"""Every knob and every table a reviewer may want to argue with, in one place.

Nothing here is behaviour: import a name instead of retyping the literal, and the
env override is the same for a container and a laptop. See AGENTS.md rule 12.
"""

from __future__ import annotations

import os

from models.claim import SourceType


def _env(name: str, default: float) -> float:
    """One coercion helper: a bad env value is a startup error, not a silent default."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return type(default)(raw)
    except ValueError as exc:
        raise SystemExit(f"{name}={raw!r} is not a {type(default).__name__}") from exc


# --- retrieval shape ---------------------------------------------------------
RRF_K = int(_env("ETYT_RRF_K", 60))                       # reciprocal-rank-fusion damping
KNN_K = int(_env("ETYT_KNN_K", 10))                       # candidates per channel
TIE_MARGIN = float(_env("ETYT_TIE_MARGIN", 0.15))         # below this, two claims disagree
FRESHNESS_HALF_LIFE_DAYS = int(_env("ETYT_FRESHNESS_HALF_LIFE_DAYS", 180))
FRESHNESS_FLOOR = float(_env("ETYT_FRESHNESS_FLOOR", 0.25))
MAX_HOPS = int(_env("ETYT_MAX_HOPS", 3))                  # traversal depth cap
MAX_NODES = int(_env("ETYT_MAX_NODES", 50))               # rows any template may return
MAX_SPANS = int(_env("ETYT_MAX_SPANS", 5))                # citations per claim
TOKEN_BUDGET = int(_env("ETYT_TOKEN_BUDGET", 2000))       # default answer budget
QUERY_TEXT_LIMIT = int(_env("ETYT_QUERY_TEXT_LIMIT", 400))  # planner input, characters
EMBED_TEXT_LIMIT = int(_env("ETYT_EMBED_TEXT_LIMIT", 4000))  # text handed to the embedder

# --- diagram reading (ADR-0012) ----------------------------------------------
DIAGRAM_ENGINE = os.getenv("ETYT_DIAGRAM_ENGINE", "onnxruntime")
# Below this OCR confidence a read line is dropped rather than cited: a wrong label is
# worse than a missing one, and the drop is named by the pipeline's own log line.
DIAGRAM_MIN_OCR_CONFIDENCE = float(_env("ETYT_DIAGRAM_MIN_OCR_CONFIDENCE", 0.55))

# Reviewed fixtures are the degradation path, never the process: above this many files a
# human-assisted extraction is refused and the automatic, fused route is the only option.
HUMAN_ASSIST_MAX_FILES = int(_env("ETYT_HUMAN_ASSIST_MAX_FILES", 20))

# --- chunking ----------------------------------------------------------------
CHUNK_TARGET_CHARS = int(_env("ETYT_CHUNK_TARGET_CHARS", 2000))
CHUNK_BATCH = int(_env("ETYT_CHUNK_BATCH", 200))

# --- models ------------------------------------------------------------------
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(_env("ETYT_EMBED_DIM", 768))              # must match schema.cypher
PLANNER_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# A cold 2.6 GB planner load outlasts 10s on CPU, so the first query after boot used to
# time out and fall back; keep_alive then holds it resident. Measured, ticks in docs/07.
MODEL_TIMEOUT_S = float(_env("ETYT_MODEL_TIMEOUT_S", 30.0))
MODEL_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")   # a cold 2.6 GB load is most of a demo
MODEL_NUM_GPU = int(_env("OLLAMA_NUM_GPU", -1))            # -1: every layer on the card

# --- source authority --------------------------------------------------------
# The tier table from docs/03. A path or pipeline overrides it where the doc says so.
AUTHORITY: dict[SourceType, float] = {
    SourceType.SCHEMA: 1.0,
    SourceType.CONFIG: 1.0,
    SourceType.API_SPEC: 0.95,
    SourceType.ADR: 0.95,
    SourceType.RELEASE: 0.90,
    SourceType.ISSUE: 0.85,
    SourceType.DESIGN_DOC: 0.80,
    SourceType.CODE: 0.75,
    SourceType.MEETING: 0.50,
    SourceType.WIKI: 0.45,
    SourceType.DIAGRAM: 0.40,   # capped: VLM extraction is the weakest link (docs/05)
    SourceType.HISTORICAL: 0.20,
    SourceType.NARRATIVE: 0.45,
}
DEFAULT_AUTHORITY = 0.45
HEADER_AUTHORITY = 0.40  # a document's own `Status:` line is one weak witness about itself

# A question's words reach a predicate two ways: cue words for the deterministic planner,
# and glosses the embedding resolver compares the whole question against. Both are ontology
# vocabulary a new domain declares once, not language heuristics in the code.
PREDICATE_CUES: dict[str, tuple[str, ...]] = {
    "HAS_COLUMN": ("field", "fields", "column", "columns"),
    "EXPOSES": ("endpoint", "endpoints", "route", "routes"),
    "OWNS": ("owner", "owners", "owned"),
    "LISTENS_ON": ("port", "ports", "listening"),
    "DEPENDS_ON": ("depends", "depend", "dependency", "dependencies"),
    "READS_FROM": ("reads", "reading"),
    "WRITES_TO": ("writes", "writing"),
    "VIOLATES": ("violates", "violation", "violations"),
    "PROHIBITS": ("prohibits", "prohibition", "prohibitions", "forbidden"),
    "SIMILAR_NAME_TO": ("join", "joins", "joinable"),
    "SUPERSEDES": ("supersedes", "superseded", "replaces"),
}

# --- vocabulary resolution ----------------------------------------------------
# The question is embedded once and compared against these glosses and every entity key
# (`graph/vocab.py`). A corpus in another language only needs its own glosses.
PREDICATE_GLOSSES: dict[str, str] = {
    "OWNS": "who owns or is responsible for a component",
    "DEPENDS_ON": "depends on another package or service",
    "DEFINED_IN": "where a service or package is defined or deployed",
    "LISTENS_ON": "which port a service listens on",
    "SETS": "a configured value or endpoint a service sets",
    "READS_FROM": "reads its data from a datastore or service",
    "WRITES_TO": "writes its data to a datastore",
    "AUTHENTICATES_VIA": "single sign-on, authentication or identity provider",
    "EXPOSES": "which endpoints or routes a service exposes",
    "IMPLEMENTS": "implements a handler or contract",
    "HAS_COLUMN": "which fields or columns a table has",
    "HAS_STATUS": "the status a document or issue declares",
    "HAS_DATE": "the date a document declares",
    "HAS_OWNER": "the owner named in a document",
    "HAS_LAST_EDITED": "when a document was last edited",
    "SUPERSEDES": "replaces or supersedes an earlier version",
    "VIOLATES": "violates a rule or breaks a contract",
    "MENTIONS": "mentions or refers to another component",
    "SHARES_SCHEMA_WITH": "shares a database schema with another service",
    "SIMILAR_NAME_TO": "has a similar name but is a different thing",
}
# Measured on the seven traps: vocabulary resolution scored 4/7, the deterministic corpus
# attestation 7/7. It is therefore opt-in, and its job is the corpus whose questions use
# words the entity keys do not contain (graph/vocab.py, docs/06-retrieval.md).
VOCAB_RESOLVE = os.getenv("ETYT_VOCAB_RESOLVE", "0") == "1"
VOCAB_K = int(_env("ETYT_VOCAB_K", 8))
VOCAB_MIN_SCORE = float(_env("ETYT_VOCAB_MIN_SCORE", 0.62))

# --- ontology ----------------------------------------------------------------
# predicate -> (subject kinds, object kinds or None for a scalar literal).
# Gate 3 rejects a claim whose predicate is absent or whose shape is out of range.
PREDICATES: dict[str, tuple[frozenset[str], frozenset[str] | None]] = {
    "OWNS": (frozenset({"Component", "Service", "Package", "Document", "Team"}), None),
    "DEPENDS_ON": (frozenset({"Package", "Service", "Component"}),
                   frozenset({"Package", "Service", "Component"})),
    "CALLS": (frozenset({"Service", "Component"}), frozenset({"Service", "Component"})),
    "DEFINED_IN": (frozenset({"Service", "Package", "Component"}), None),
    "LISTENS_ON": (frozenset({"Service"}), None),
    "SETS": (frozenset({"Service"}), None),
    "READS_FROM": (frozenset({"Service", "Component"}), frozenset({"Service", "Datastore"})),
    "WRITES_TO": (frozenset({"Service", "Component"}), frozenset({"Datastore"})),
    "AUTHENTICATES_VIA": (frozenset({"Service", "Component"}), frozenset({"Service"})),
    "EXPOSES": (frozenset({"Service"}), None),
    "IMPLEMENTS": (frozenset({"Service", "Component"}), None),
    "HAS_COLUMN": (frozenset({"Table"}), None),
    "HAS_STATUS": (frozenset({"Document", "Issue", "Release", "Meeting"}), None),
    "HAS_DATE": (frozenset({"Document", "Issue", "Release", "Meeting"}), None),
    "HAS_OWNER": (frozenset({"Document", "Issue", "Release", "Meeting"}), None),
    "HAS_LAST_EDITED": (frozenset({"Document", "Issue", "Release", "Meeting"}), None),
    "SUPERSEDES": (frozenset({"Document"}), frozenset({"Document"})),
    "VIOLATES": (frozenset({"Service", "Component"}), None),
    "MENTIONS": (frozenset({"Document"}), frozenset({"Service", "Component", "Package", "Table"})),
    "SHARES_SCHEMA_WITH": (frozenset({"Service"}), frozenset({"Service"})),
    "SIMILAR_NAME_TO": (frozenset({"Service", "Component", "Entity"}),
                        frozenset({"Service", "Component", "Entity"})),
    # Diagram evidence (ADR-0012). A picture is a Document; what it says is text read
    # from a region, and a diagram node is an entity the picture shows.
    "HAS_DECLARED_TYPE": (frozenset({"Table"}), None),
    "APPEARS_IN": (frozenset({"Table", "Component", "Service", "Datastore"}),
                   frozenset({"Document"})),
}

# --- transport ---------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(_env("PORT", 8000))
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "etyt-context")
NEO4J_TIMEOUT_S = float(_env("ETYT_NEO4J_TIMEOUT_S", 10.0))

# --- How hard to look -------------------------------------------------------
# One number decides how many channels are paid for and how many answers the request
# promises. Semi-automatic: the planner starts at `AUTO_EFFORT`/`AUTO_EFFORT_NAMED`, and
# the caller may pin any level in the request. Lowering it is always allowed; the gates
# (status, time, span) never relax, so extra effort can only find more evidence, never
# weaker evidence.
EFFORT_MAX = 4
AUTO_EFFORT = 2        # question names nothing: look by meaning as well as by key
AUTO_EFFORT_NAMED = 1  # question names an identifier: the exact match is already the answer
EFFORT_MIN_RESULTS = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3}
EFFORT_SEMANTIC_K = {0: 0, 1: 8, 2: 16, 3: 32, 4: 64}
CLAIM_INDEX = "claim_embedding"
# Passages are the layer below claims: verbatim corpus text, cited and hash-verified. Most
# of a corpus never becomes a claim, and without this an unmatchable question loses it.
EFFORT_EVIDENCE = {0: 0, 1: 2, 2: 3, 3: 5, 4: 8}
EVIDENCE_TEXT_LIMIT = 600
# Structural noise (`}` from a lock file) is a keyword hit and not evidence: require shape.
EVIDENCE_MIN_CHARS = 60
# A passage must be relevant, not merely short: cosine >= Nemo's floor for a vector hit, or
# at least one content word shared with the question for a keyword hit (scale-free).
EVIDENCE_MIN_COSINE = 0.62
EVIDENCE_MIN_RATIO = 0.6
# Measured: claim statements score 0.72-0.84 with almost no spread, so a floor separates
# junk from near-misses but cannot rank. The cap is what keeps a vague question from
# returning a pile of real-but-unrelated facts: recall widens, the answer stays readable.
EFFORT_MIN_SCORE = 0.70
# Per level, because one global cap made levels 1-4 indistinguishable when measured.
EFFORT_MAX_RESULTS = {0: 0, 1: 2, 2: 3, 3: 4, 4: 5}

# --- How much to say back ----------------------------------------------------
# Effort is how hard the service looks; detail is how much of what it found it returns.
# One knob, three named levels, so a caller never assembles the shape field by field.
DETAIL_LEVELS = ("low", "medium", "high")
# REST and the web UI keep the full envelope they always had; MCP pays per token, so an
# agent that does not ask for detail gets the smallest answer that is still honest.
DETAIL_DEFAULT = "medium"
DETAIL_DEFAULT_MCP = "low"
DETAIL_EXCERPT_CHARS = 320  # what one quoted citation may add at `high`
# Provenance is only worth bytes when something is being debugged or audited.
DETAIL_CLAIM_FIELDS = {
    "low": (),
    "medium": ("id", "subject", "predicate", "polarity", "why_not_valid"),
    "high": (
        "id",
        "subject",
        "predicate",
        "polarity",
        "why_not_valid",
        "extractor",
        "extractor_version",
        "observed_at",
        "modality",
        "authority",
    ),
}

# How sure the *extractor* is that it read the source correctly - not how sure we are that
# the claim is true, which is what `status` and the authority table are for. A SQL ALTER
# parsing `ADD COLUMN` is exact; a prose heuristic that spotted a name is not. All six used
# to be 1.0, which made the number in the UI meaningless.
EXTRACTOR_CONFIDENCE: dict[str, float] = {
    "sql.alter": 0.98,        # exact DDL parse, but the file may be a draft
    "json.config-map": 0.97,  # exact JSON, key order irrelevant
    "markdown.status": 0.95,  # `Status:` and `Date:` headers are explicit
    "config.deploy": 0.98,    # compose/package/CODEOWNERS are literal
    "api.spec": 0.96,         # OpenAPI paths and GraphQL fields are declared
    "prose.mention": 0.70,    # a name appeared in running text
}
DEFAULT_EXTRACTOR_CONFIDENCE = 0.80
