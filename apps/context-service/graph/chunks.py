"""Chunk the corpus and index it for hybrid search.

Text is the retrieval unit only: chunks are rebuildable from `(path, lines)` and are never
cited. Embeddings are optional — BM25 over the same text works without a model, so the
service still answers when Ollama is absent.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from neo4j import Driver

TARGET_CHARS = 2000  # ~500 tokens; recursive splitting beat semantic chunking in the 2026 benchmarks
PROSE = ("docs", "wiki", "meeting-notes", "issues", "incidents", "releases", "api-specs", "archive")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _split(text: str) -> list[tuple[str, str]]:
    """Heading-aware split: (heading_path, body). Falls back to character windows."""
    chunks: list[tuple[str, str]] = []
    heading, body = "", []
    for line in text.splitlines():
        match = HEADING.match(line)
        if match and "".join(body).strip():
            chunks.append((heading, "\n".join(body).strip()))
            body = []
        if match:
            heading = match.group(2).strip()
        body.append(line)
    if "".join(body).strip():
        chunks.append((heading, "\n".join(body).strip()))
    return [(h, b) for h, b in chunks if b]


def _windows(body: str) -> list[str]:
    if len(body) <= TARGET_CHARS:
        return [body]
    return [body[i : i + TARGET_CHARS] for i in range(0, len(body), TARGET_CHARS)]


def rows(root: Path) -> list[dict]:
    out: list[dict] = []
    for directory in PROSE:
        for path in sorted((root / directory).rglob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            relative = path.relative_to(root).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            for heading, body in _split(text):
                for part in _windows(body):
                    out.append(
                        {
                            "id": hashlib.sha256(f"{relative}|{heading}|{part[:64]}".encode()).hexdigest()[:16],
                            "text": f"{heading}\n{part}".strip() if heading else part,
                            "heading": heading,
                            "tokens": len(part) // 4,
                            "path": relative,
                            "hash": digest,
                        }
                    )
    return out


UPSERT = """
UNWIND $chunks AS c
MERGE (ch:Chunk {id: c.id})
SET ch.text = c.text, ch.heading_path = c.heading, ch.token_count = c.tokens
MERGE (src:Source {path: c.path})
SET src.content_hash = c.hash
MERGE (ch)-[:IN]->(src)
"""


def index(driver: Driver, root: Path, embed=None) -> int:
    """Write chunks; `embed(text) -> list[float] | None` adds vectors when a model exists."""
    chunks = rows(root)
    if embed is not None:
        for chunk in chunks:
            vector = embed(chunk["text"])
            if vector:
                chunk["embedding"] = vector
    with driver.session() as session:
        session.run(UPSERT, chunks=chunks).consume()
    return len(chunks)
