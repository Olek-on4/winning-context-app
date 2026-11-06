"""Deterministic extraction: the facts that a parser can read without a model.

Scope is deliberately narrow — SQL migrations and `config/ports.json`. Between them they
cover the schema-drift trap and the service→port map, with a verified span per claim and
no chance of invention. Everything else stays fixture- or lane-A territory.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from models.claim import ClaimRecord, EntityRef, Modality, Polarity, SourceType, Span

RENAME = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+RENAME\s+COLUMN\s+(\w+)\s+TO\s+(\w+)", re.I)
ADD = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.I)
AUTHORITY = {SourceType.SCHEMA: 1.0, SourceType.CONFIG: 1.0}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _last_commit_day(root: Path, path: Path) -> date | None:
    """Migrations carry no date; the commit that added them is the best signal we have."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cs", "--", path.relative_to(root).as_posix()],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        return date.fromisoformat(out) if out else None
    except (ValueError, OSError):
        return None


def _line_of(lines: list[str], needle: re.Pattern, needle_text: str) -> int:
    for number, line in enumerate(lines, start=1):
        if needle.search(line) and needle_text.lower() in line.lower():
            return number
    return 1


def _span(root: Path, path: Path, lines: list[str], line: int, digest: str) -> Span:
    return Span(
        path=path.relative_to(root).as_posix(),
        start_line=line,
        end_line=line,
        content_hash=digest,
    )


def migrations(root: Path) -> list[ClaimRecord]:
    out: list[ClaimRecord] = []
    for path in sorted((root / "apps").rglob("migrations/*.sql")):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        digest = _sha(path)
        observed = _last_commit_day(root, path)
        for match in RENAME.finditer(text):
            table, old, new = match.groups()
            line = _line_of(lines, re.compile(re.escape(old), re.I), old)
            base = dict(
                subject=EntityRef(kind="Table", key=table),
                predicate="HAS_COLUMN",
                observed_at=observed,
                valid_from=observed,
                observed_precision="day",
                evidence=[_span(root, path, lines, line, digest)],
                confidence=1.0,
                authority=AUTHORITY[SourceType.SCHEMA],
                source_type=SourceType.SCHEMA,
                extractor="schema.migration",
            )
            out.append(ClaimRecord(object=old, polarity=Polarity.NEGATES, **base))
            out.append(ClaimRecord(object=new, polarity=Polarity.ASSERTS, **base))
        for match in ADD.finditer(text):
            table, column = match.groups()
            if any(column in r.groups() for r in RENAME.finditer(text)):
                continue  # already covered by the rename rule
            line = _line_of(lines, re.compile(re.escape(column), re.I), column)
            out.append(
                ClaimRecord(
                    subject=EntityRef(kind="Table", key=table),
                    predicate="HAS_COLUMN",
                    object=column,
                    observed_at=observed,
                    valid_from=observed,
                    evidence=[_span(root, path, lines, line, digest)],
                    confidence=1.0,
                    authority=AUTHORITY[SourceType.SCHEMA],
                    source_type=SourceType.SCHEMA,
                    extractor="schema.migration",
                )
            )
    return out


def ports(root: Path) -> list[ClaimRecord]:
    path = root / "config" / "ports.json"
    if not path.is_file():
        return []
    digest = _sha(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    observed = _last_commit_day(root, path)
    out: list[ClaimRecord] = []
    for name, port in json.loads(path.read_text(encoding="utf-8")).items():
        line = _line_of(lines, re.compile(re.escape(name), re.I), name)
        out.append(
            ClaimRecord(
                subject=EntityRef(kind="Service", key=name),
                predicate="LISTENS_ON",
                object=str(port),
                modality=Modality.FACT,
                observed_at=observed,
                valid_from=observed,
                evidence=[_span(root, path, lines, line, digest)],
                confidence=1.0,
                authority=AUTHORITY[SourceType.CONFIG],
                source_type=SourceType.CONFIG,
                extractor="config.ports",
            )
        )
    return out


def extract(root: Path) -> list[ClaimRecord]:
    claims = [*migrations(root), *ports(root)]
    deduped: dict[str, ClaimRecord] = {}
    for claim in claims:
        deduped.setdefault(claim.claim_id, claim)
    return list(deduped.values())
