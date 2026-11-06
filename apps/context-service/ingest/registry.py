"""The plug-in point: a pipeline claims file paths and emits claims about them.

Nothing in this module knows what the corpus is. Adding a data type means adding one
`Pipeline` and registering it — no edits anywhere else, which is the property that makes
the service data-agnostic (ADR-0009).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Protocol

from ingest.gates import dated_by_reference
from models.claim import ClaimRecord, DocStatus, EntityRef, Modality, Polarity, SourceType, Span
from sources import Root

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


class Pipeline(Protocol):
    name: str

    def matches(self, path: Path) -> bool: ...

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]: ...


def _observed(root: Root, relative: Path) -> date | None:
    """Migrations and config carry no date; the commit that added them is the best signal."""
    import subprocess

    if relative.is_absolute():  # git pathspecs are repo-relative; callers pass either form
        relative = relative.relative_to(root.path)
    try:
        out = subprocess.run(
            ["git", "-C", str(root.path), "log", "-1", "--format=%cs", "--", relative.as_posix()],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        return date.fromisoformat(out) if out else None
    except (ValueError, OSError):
        return None


def _line_containing(path: Path, needle: str) -> int:
    """Stream to the first matching line; a 10 MB file costs one pass, not one copy."""
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            if pattern.search(line):
                return number
    return 1


def _claim(root: Root, relative: Path, line: int, digest: str, **fields) -> ClaimRecord:
    if relative.is_absolute():  # a pointer is root-relative, never a machine path
        relative = relative.relative_to(root.path)
    return ClaimRecord(
        evidence=[Span(path=root.pointer(relative), start_line=line, end_line=line, content_hash=digest)],
        **fields,
    )


class SqlAlter:
    """Schema drift in any SQL tree: renames negate the old column and assert the new one."""

    name = "sql.alter"

    def matches(self, path: Path) -> bool:
        return path.suffix == ".sql"

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]:
        text = path.read_text(encoding="utf-8", errors="replace")  # SQL files are small; spans still stream
        # The release that ships a migration is a better date than the commit that added it.
        observed = dated_by_reference(root, path.name) or _observed(root, path)
        common = dict(
            observed_at=observed, valid_from=observed, observed_precision="day",
            confidence=1.0, authority=1.0, source_type=SourceType.SCHEMA, extractor=self.name,
        )
        for table, old, new in RENAME.findall(text):
            line = _line_containing(path, old)
            yield _claim(root, path, line, digest, subject=EntityRef(kind="Table", key=table),
                         predicate="HAS_COLUMN", object=old, polarity=Polarity.NEGATES, **common)
            yield _claim(root, path, line, digest, subject=EntityRef(kind="Table", key=table),
                         predicate="HAS_COLUMN", object=new, **common)
        for table, column in ADD.findall(text):
            if any(column == r[2] for r in RENAME.findall(text)):
                continue
            yield _claim(root, path, _line_containing(path, column), digest,
                         subject=EntityRef(kind="Table", key=table), predicate="HAS_COLUMN",
                         object=column, **common)


class JsonConfigMap:
    """Any JSON object of name → scalar is a mapping; `ports.json` is just one of them."""

    name = "json.config-map"

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
            yield _claim(
                root, path, _line_containing(path, name), digest,
                subject=EntityRef(kind="Service", key=str(name)), predicate=predicate, object=str(value),
                modality=Modality.FACT, observed_at=observed, valid_from=observed,
                confidence=1.0, authority=1.0, source_type=SourceType.CONFIG, extractor=self.name,
            )


class MarkdownStatus:
    """`Date:`/`Status:` headers in any markdown tree — a decision's own claim about itself."""

    name = "markdown.status"
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
                    root, path, number, digest,
                    subject=EntityRef(kind="Document", key=root.pointer(path.relative_to(root.path))),
                    predicate=f"HAS_{field.upper()}", object=value,
                    modality=Modality.FACT, observed_at=observed, valid_from=observed,
                    confidence=1.0, authority=0.4,
                    source_type=kind,
                    doc_status=declared_status(value) if field == "status" else None,
                    extractor=self.name,
                )


class DeployConfig:
    """compose services, manifest dependencies and CODEOWNERS — all deterministic."""

    name = "config.deploy"
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
        common = dict(observed_at=observed, valid_from=observed, confidence=1.0,
                      authority=1.0, source_type=SourceType.CONFIG, extractor=self.name)
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
                    yield _claim(root, path, _line_containing(path, name), digest,
                                 subject=EntityRef(kind="Package", key=package),
                                 predicate="DEPENDS_ON", object=name, **common)
            return
        if path.name == "CODEOWNERS":
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = self.OWNER.match(line)
                if match:
                    yield _claim(root, path, number, digest,
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
                yield _claim(root, path, number, digest,
                             subject=EntityRef(kind="Service", key=current),
                             predicate="DEFINED_IN", object=root.pointer(path.relative_to(root.path)), **common)
                continue
            if current and line.strip().startswith("depends_on"):
                in_depends = True
                continue
            if in_depends:
                dep = self.DEPENDS.match(line)
                if dep:
                    yield _claim(root, path, number, digest,
                                 subject=EntityRef(kind="Service", key=current),
                                 predicate="DEPENDS_ON", object=dep.group(1), **common)
                elif line.strip() and not line.startswith(" " * 6):
                    in_depends = False


PIPELINES: list[Pipeline] = [SqlAlter(), JsonConfigMap(), MarkdownStatus(), DeployConfig()]


def register(pipeline: Pipeline) -> None:
    """One line to plug in a new data type."""
    PIPELINES.append(pipeline)


def route(path: Path) -> list[Pipeline]:
    return [p for p in PIPELINES if p.matches(path)]


def extract(root: Root) -> list[ClaimRecord]:
    """Walk one root, stream its hashes, and let pipelines claim what they recognise."""
    claims: list[ClaimRecord] = []
    for relative, digest in _walk(root):
        absolute = root.path / relative
        for pipeline in route(absolute):
            # The graph refuses an undated claim; dropping it here keeps that an ingest concern.
            claims.extend(c for c in pipeline.extract(root, absolute, digest) if c.observed_at is not None)
    return claims


def _walk(root: Root) -> Iterable[tuple[Path, str]]:
    from sources import iter_files

    yield from iter_files(root)
