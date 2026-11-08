"""The plug-in point: a pipeline claims file paths and emits claims about them.

Nothing in this module knows what the corpus is. Adding a data type means adding one
`Pipeline` and registering it — no edits anywhere else, which is the property that makes
the service data-agnostic (ADR-0009).
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Protocol, TextIO

from ingest.gates import dated_by_reference
from ingest.optin import OptIn, agree
from models.claim import ClaimRecord, DocStatus, EntityRef, Modality, Polarity, SourceType, Span
from settings import AUTHORITY, DEFAULT_EXTRACTOR_CONFIDENCE, EXTRACTOR_CONFIDENCE, HEADER_AUTHORITY
from sources import KINDS, Root, iter_files

# One span per claim by construction: the extractor locates the line, it does not quote.
RENAME = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+RENAME\s+COLUMN\s+(\w+)\s+TO\s+(\w+)", re.IGNORECASE)
ADD = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.IGNORECASE)
KEY_VALUE = re.compile(r'^\s*"([A-Za-z0-9_.\- ]+)"\s*:\s*(?:"[^"]*"|-?\d+(?:\.\d+)?|true|false)\s*,?\s*$')


_PATH_TYPES: tuple[tuple[str, SourceType], ...] = (
    ("docs/adr/", SourceType.ADR),
    ("wiki/", SourceType.WIKI),
    ("meeting-notes/", SourceType.MEETING),
    ("issues/", SourceType.ISSUE),
    ("incidents/", SourceType.ISSUE),
    ("releases/", SourceType.RELEASE),
    ("api-specs/history/", SourceType.HISTORICAL),
    ("api-specs/", SourceType.API_SPEC),
    ("archive/", SourceType.HISTORICAL),
    ("docs/", SourceType.DESIGN_DOC),
)


def source_type_for(path: Path) -> SourceType:
    """Path first: in this corpus the directory says more than the extension."""
    posix = path.as_posix()
    for prefix, kind in _PATH_TYPES:
        if posix.startswith(prefix) or f"/{prefix}" in posix:
            return kind
    if path.suffix == ".sql":
        return SourceType.SCHEMA
    if path.suffix in {".json", ".yaml", ".yml", ".toml"}:
        return SourceType.CONFIG
    if path.suffix == ".md":
        return SourceType.NARRATIVE
    return SourceType.CODE


def declared_status(header: str) -> DocStatus | None:
    """`Status: Accepted` caps what the document may claim (issue 2)."""
    value = header.strip().lower()
    for status in DocStatus:
        if value.startswith(status.value):
            return status
    return None


def _confidence(extractor: str) -> float:
    """Per-extractor extraction certainty; see settings.EXTRACTOR_CONFIDENCE."""
    return EXTRACTOR_CONFIDENCE.get(extractor, DEFAULT_EXTRACTOR_CONFIDENCE)


class Pipeline(Protocol):
    name: str
    # Set when the pipeline needs a dependency the default install does not carry; the
    # walker then asks before it touches a single file (ingest/optin.py).
    opt_in: OptIn | None

    def matches(self, path: Path) -> bool: ...

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]: ...


def _observed(root: Root, relative: Path) -> date | None:
    """A file's date: git, then its own `Date:` line, then its mtime (issue 84).

    A non-git tree used to yield no date and therefore no claims at all. A declared
    `Date:` beats mtime; mtime is the last resort, weaker but still evidence the file
    exists now — silence is never the better answer.
    """
    import subprocess

    if relative.is_absolute():  # git pathspecs are repo-relative; callers pass either form
        relative = relative.relative_to(root.path)
    try:
        out = subprocess.run(
            ["git", "-C", str(root.path), "log", "-1", "--format=%cs", "--", relative.as_posix()],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        if out:
            return date.fromisoformat(out)
    except (ValueError, OSError):
        pass
    path = root.path / relative
    declared = _declared_date(path)
    if declared is not None:
        return declared
    try:
        return date.fromtimestamp(path.stat().st_mtime)
    except OSError as error:
        print(f"gap {root.pointer(relative)}: no git history, no Date: line, no mtime ({error})", file=sys.stderr)
        return None


_DATE_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:date|last[ -]edited|last[ -]modified)\s*:\s*(\d{4}-\d{2}-\d{2})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _declared_date(path: Path) -> date | None:
    """`Date: 2026-03-01` in the header: a document dating itself outranks its mtime."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = "".join(itertools.islice(handle, 40))
    except OSError:
        return None
    match = _DATE_LINE.search(head)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        print(f"gap {path.name}: Date: line is not ISO-8601 ({match.group(1)})", file=sys.stderr)
        return None


def _line_containing(path: Path, needle: str) -> tuple[int, str]:
    """First line matching `needle`, with its text: the gate quotes what it verified."""
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            if pattern.search(line):
                return number, line.rstrip("\n")
    return 1, ""  # nothing to quote: the claim loads ungeated instead of citing a wrong line


def _claim(root: Root, relative: Path, line: int, digest: str, excerpt: str | None = None, **fields) -> ClaimRecord:
    if relative.is_absolute():  # a pointer is root-relative, never a machine path
        relative = relative.relative_to(root.path)
    return ClaimRecord(
        evidence=[Span(path=root.pointer(relative), start_line=line, end_line=line, content_hash=digest)],
        excerpt=excerpt or None,
        **fields,
    )


class SqlAlter:
    """Schema drift in any SQL tree: renames negate the old column and assert the new one."""

    name = "sql.alter"
    # Bump when this extractor's output changes: claim ids encode it, and a load replaces
    # the extractor's other versions rather than adding a second truth beside them.
    version = "1"

    def matches(self, path: Path) -> bool:
        return path.suffix == ".sql"

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]:
        text = path.read_text(encoding="utf-8", errors="replace")  # SQL files are small; spans still stream
        # The release that ships a migration is a better date than the commit that added it.
        observed = dated_by_reference(root, path.name) or _observed(root, path)
        common = dict(
            observed_at=observed, valid_from=observed, observed_precision="day",
            confidence=_confidence(self.name), authority=AUTHORITY[SourceType.SCHEMA], source_type=SourceType.SCHEMA, extractor=self.name, extractor_version=self.version,
        )
        for table, old, new in RENAME.findall(text):
            line, quote = _line_containing(path, old)
            yield _claim(root, path, line, digest, quote, subject=EntityRef(kind="Table", key=table),
                         predicate="HAS_COLUMN", object=old, polarity=Polarity.NEGATES, **common)
            yield _claim(root, path, line, digest, quote, subject=EntityRef(kind="Table", key=table),
                         predicate="HAS_COLUMN", object=new, **common)
        for table, column in ADD.findall(text):
            if any(column == r[2] for r in RENAME.findall(text)):
                continue
            line, quote = _line_containing(path, column)
            yield _claim(root, path, line, digest, quote, subject=EntityRef(kind="Table", key=table),
                         predicate="HAS_COLUMN", object=column, **common)


class JsonConfigMap:
    """Any JSON object of name → scalar is a mapping; `ports.json` is just one of them."""

    name = "json.config-map"
    version = "1"

    def matches(self, path: Path) -> bool:
        return path.suffix == ".json" and path.name in {"ports.json", "services.json", "endpoints.json"}

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        if not isinstance(data, dict):
            return
        observed = _observed(root, path)
        kind = "Port" if path.name == "ports.json" else "Endpoint"
        predicate = "LISTENS_ON" if kind == "Port" else "SETS"
        for name, value in data.items():
            if not isinstance(value, (str, int, float)):
                continue
            line, quote = _line_containing(path, name)
            yield _claim(
                root, path, line, digest, quote,
                subject=EntityRef(kind="Service", key=str(name)), predicate=predicate, object=str(value),
                modality=Modality.FACT, observed_at=observed, valid_from=observed,
                confidence=_confidence(self.name), authority=AUTHORITY[SourceType.CONFIG], source_type=SourceType.CONFIG, extractor=self.name, extractor_version=self.version,
            )


class MarkdownStatus:
    """`Date:`/`Status:` headers in any markdown tree — a decision's own claim about itself."""

    name = "markdown.status"
    version = "1"
    HEADER = re.compile(r"^\s*(?:[-*]\s*)?(Date|Status|Owner|Last edited)\s*:\s*(.+)$", re.IGNORECASE)

    def matches(self, path: Path) -> bool:
        return path.suffix == ".md"

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]:
        observed = _observed(root, path.relative_to(root.path))
        if observed is None:  # a claim with no time signal cannot be resolved
            return
        kind = source_type_for(path.relative_to(root.path))
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                if number > 40:  # headers live at the top; stop reading early
                    return
                match = self.HEADER.match(line)
                if not match:
                    continue
                field, value = match.group(1).lower().replace(" ", "_"), match.group(2).strip()
                yield _claim(
                    root, path, number, digest, line.rstrip("\n"),
                    subject=EntityRef(kind="Document", key=root.pointer(path.relative_to(root.path))),
                    predicate=f"HAS_{field.upper()}", object=value,
                    modality=Modality.FACT, observed_at=observed, valid_from=observed,
                    confidence=_confidence(self.name), authority=HEADER_AUTHORITY,
                    source_type=kind,
                    doc_status=declared_status(value) if field == "status" else None,
                    extractor=self.name, extractor_version=self.version,
                )


class DeployConfig:
    """compose services, manifest dependencies and CODEOWNERS — all deterministic."""

    name = "config.deploy"
    version = "1"
    SERVICE = re.compile(r"^  ([a-z0-9][\w-]*):\s*$")
    DEPENDS = re.compile(r"^\s+-\s+([\w-]+)\s*$")
    OWNER = re.compile(r"^\s*/?([\w./-]+?)/?\s+@([\w./-]+)\s*$")
    DEP_NAME = re.compile(r'"(@?[\w./-]+)"\s*:\s*"[~^>=<]*[\d.]')

    def matches(self, path: Path) -> bool:
        return path.name in {"compose.yaml", "compose.yml", "CODEOWNERS"} or path.name == "package.json"

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]:
        observed = _observed(root, path.relative_to(root.path))
        if observed is None:
            return
        common = dict(observed_at=observed, valid_from=observed, confidence=_confidence(self.name),
                      authority=AUTHORITY[SourceType.CONFIG], source_type=SourceType.CONFIG, extractor=self.name, extractor_version=self.version)
        if path.name == "package.json":
            # Parse the manifest: a regex over JSON lines counts `"version": "1.0.0"`
            # as a dependency, which it is not.
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return
            package = path.parent.name or "root"
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for name in (data.get(section) or {}):
                    line, quote = _line_containing(path, name)
                    yield _claim(root, path, line, digest, quote,
                                 subject=EntityRef(kind="Package", key=package),
                                 predicate="DEPENDS_ON", object=name, **common)
            return
        if path.name == "CODEOWNERS":
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = self.OWNER.match(line)
                if match:
                    yield _claim(root, path, number, digest, line,
                                 subject=EntityRef(kind="Component", key=match.group(1)),
                                 predicate="OWNS", object=match.group(2), **common)
            return
        # compose: service names are the facts; depends_on arrives as DEPENDS_ON edges
        current = None
        in_depends = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            service = self.SERVICE.match(line)
            if service:
                current, in_depends = service.group(1), False
                yield _claim(root, path, number, digest, line,
                             subject=EntityRef(kind="Service", key=current),
                             predicate="DEFINED_IN", object=root.pointer(path.relative_to(root.path)), **common)
                continue
            if current and line.strip().startswith("depends_on"):
                in_depends = True
                continue
            if in_depends:
                dep = self.DEPENDS.match(line)
                if dep:
                    yield _claim(root, path, number, digest, line,
                                 subject=EntityRef(kind="Service", key=current),
                                 predicate="DEPENDS_ON", object=dep.group(1), **common)
                elif line.strip() and not line.startswith(" " * 6):
                    in_depends = False


class ApiSpec:
    """OpenAPI documents and GraphQL SDL: an interface is a claim about what a service exposes.

    Deterministic by construction — a route is in the spec or it is not — so authority is
    high and confidence is 1.0 (docs/05 ApiSpecPipeline). A spec under `history/` is a
    superseded contract by path rule, exactly like the corpus trap T3.
    """

    name = "api.spec"
    version = "1"
    METHOD = re.compile(r"^(get|post|put|patch|delete|head|options)$", re.IGNORECASE)
    GQL_TYPE = re.compile(r"^\s*type\s+(\w+)")
    GQL_FIELD = re.compile(r"^\s+(\w+)\s*[(:]")

    def matches(self, path: Path) -> bool:
        if path.suffix == ".graphql":
            return True
        return path.suffix in {".json", ".yaml", ".yml"} and "api-specs" in path.parts

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]:
        relative = path.relative_to(root.path)
        observed = dated_by_reference(root, path.name) or _observed(root, path)
        if observed is None:
            return
        historical = "history/" in relative.as_posix() or "archive/" in relative.as_posix()
        service = path.stem.split(".")[0]
        common = dict(
            observed_at=observed, valid_from=observed, confidence=_confidence(self.name),
            authority=AUTHORITY[SourceType.HISTORICAL if historical else SourceType.API_SPEC],
            source_type=SourceType.HISTORICAL if historical else SourceType.API_SPEC,
            extractor=self.name, extractor_version=self.version,
        )
        if path.suffix == ".graphql":
            yield from self._sdl(root, path, digest, service, common)
        else:
            yield from self._openapi(root, path, digest, service, common)

    def _openapi(self, root: Root, path: Path, digest: str, service: str, common: dict) -> Iterable[ClaimRecord]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        paths = data.get("paths") if isinstance(data, dict) else None
        if not isinstance(paths, dict):
            return  # a config map, not a spec: another pipeline owns it
        for route, operations in paths.items():
            methods = [m for m in (operations or {}) if isinstance(operations, dict) and self.METHOD.match(str(m))]
            if not methods:
                methods = ["ANY"]
            line, quote = _line_containing(path, str(route))
            for method in methods:
                yield _claim(root, path, line, digest, quote,
                             subject=EntityRef(kind="Service", key=service),
                             predicate="EXPOSES", object=f"{method.upper()} {route}", **common)

    def _sdl(self, root: Root, path: Path, digest: str, service: str, common: dict) -> Iterable[ClaimRecord]:
        current: str | None = None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                type_match = self.GQL_TYPE.match(line)
                if type_match:
                    current = type_match.group(1)
                    continue
                if current is None:
                    continue
                if line.strip().startswith("}"):
                    current = None
                    continue
                field_match = self.GQL_FIELD.match(line)
                if field_match:
                    yield _claim(root, path, number, digest, line,
                                 subject=EntityRef(kind="Service", key=service),
                                 predicate="EXPOSES", object=f"{current}.{field_match.group(1)}", **common)


PIPELINES: list[Pipeline] = [SqlAlter(), JsonConfigMap(), MarkdownStatus(), DeployConfig(), ApiSpec()]

# The diagram reader is ungated: its stack carries no strong copyleft (ADR-0013), and a
# corpus of images must not be invisible just because nobody agreed to a licence.
from ingest.diagram import DiagramText

PIPELINES.append(DiagramText())


def register(pipeline: Pipeline) -> None:
    """One line to plug in a new data type."""
    PIPELINES.append(pipeline)


def route(path: Path) -> list[Pipeline]:
    return [p for p in PIPELINES if p.matches(path)]


def extract(
    root: Root,
    *,
    accepted: frozenset[str] = frozenset(),
    rejected: frozenset[str] = frozenset(),
    ask: Callable[[str], str] | None = None,
    stream: TextIO = sys.stderr,
    record: dict[str, str] | None = None,
) -> list[ClaimRecord]:
    """Walk one root, stream its hashes, and let pipelines claim what they recognise.

    Two phases, because consent has to be asked before work rather than during it: the
    walk collects what each pipeline would claim, the gated pipelines are resolved once,
    and only then does anything extract.
    """
    def claimed_by_pipeline(path: Path) -> bool:
        """A file some pipeline claims is yielded instead of refused as non-text.

        Gated or not: the default diagram reader is ungated by design, and restricting this
        to opt-in pipelines was the defect that made the consent prompt never fire.
        """
        return any(p.matches(path) for p in PIPELINES)

    routed: list[tuple[Path, str, list[Pipeline]]] = []
    for relative, digest in iter_files(root, claimable=claimed_by_pipeline):
        absolute = root.path / relative
        routed.append((absolute, digest, route(absolute)))

    allowed: dict[str, bool] = {}
    for pipeline in sorted({p.name: p for _, _, ps in routed for p in ps}.values(), key=lambda p: p.name):
        opt_in = getattr(pipeline, "opt_in", None)  # optional: ungated pipelines say nothing
        if opt_in is None:
            continue
        count = sum(1 for _, _, ps in routed if pipeline in ps)
        decision = agree(opt_in, files=count, accepted=accepted, rejected=rejected, ask=ask, stream=stream)
        allowed[pipeline.name] = decision.allowed
        if record is not None:  # the consent itself is a record, not only a prompt
            record[pipeline.name] = f"{'accepted' if decision.allowed else 'declined'} ({decision.reason})"
        if not decision.allowed:
            # A skipped capability is named like any other gap: "zero claims" stays auditable.
            print(f"skipped {count} file(s) for {pipeline.name}: opt-in declined ({decision.reason})", file=stream)

    claims: list[ClaimRecord] = []
    declared = KINDS.get(root.kind) if root.kind else None
    for absolute, digest, pipelines in routed:
        for pipeline in pipelines:
            if allowed.get(pipeline.name) is False:
                continue
            for claim in pipeline.extract(root, absolute, digest):
                if claim.observed_at is None:
                    # The graph refuses an undated claim, so this is a gap, not a filter:
                    # naming it keeps "zero claims" auditable instead of silent (issue 84).
                    span = claim.evidence[0]
                    print(f"gap {span.path}:{span.start_line}: undated {claim.predicate} dropped", file=sys.stderr)
                    continue
                if declared is not None and claim.source_type is SourceType.NARRATIVE:
                    # A declared root outranks path guessing; content evidence outranks both.
                    claim = claim.model_copy(update={"source_type": declared})
                claims.append(claim)
    return claims
