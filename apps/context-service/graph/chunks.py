"""Chunk any text tree for hybrid search — streamed, batched, root-agnostic.

Chunks are the retrieval unit only: rebuildable from a pointer, never cited. Text is
read one line at a time and written to the graph in batches, so a 10 MB file costs a
line buffer, not 10 MB of RAM.
"""

from __future__ import annotations

import hashlib
import re

from neo4j import Driver

from sources import Root, iter_files

TARGET_CHARS = 2000  # ~500 tokens; recursive splitting beat semantic chunking in 2026 benchmarks
BATCH = 200
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

UPSERT = """
UNWIND $chunks AS c
MERGE (ch:Chunk {id: c.id})
SET ch.text = c.text, ch.heading_path = c.heading, ch.token_count = c.tokens,
    ch.embedding = c.embedding
MERGE (src:Source {path: c.path})
SET src.content_hash = c.hash
MERGE (ch)-[:IN]->(src)
"""


def _windows(pointer: str, digest: str, heading: str, text: str, base: int):
    """`base` is the char offset of `text` in its file, so ids stay unique when one
    heading yields several windows — a per-body index would collide and lose text."""
    for index in range(0, len(text), TARGET_CHARS):
        part = text[index : index + TARGET_CHARS]
        yield {
            "id": hashlib.sha256(f"{pointer}|{heading}|{base + index}".encode()).hexdigest()[:16],
            "text": f"{heading}\n{part}".strip() if heading else part,
            "heading": heading,
            "tokens": len(part) // 4,
            "path": pointer,
            "hash": digest,
        }


def _append_windows(out: list[dict], pointer: str, digest: str, heading: str, body: list[str], base: int) -> int:
    """Append this body's windows; return the char length they advanced the file by."""
    text = "\n".join(body).strip()
    if not text:
        return 0
    out.extend(_windows(pointer, digest, heading, text, base))
    return len(text)


def chunks_for(root: Root) -> list[dict]:
    """Heading-aware, line-streamed. One list per file, flushed by the caller."""
    out: list[dict] = []
    for relative, digest in iter_files(root):
        pointer = root.pointer(relative)
        heading, body, offset = "", [], 0
        with (root.path / relative).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = HEADING.match(line)
                if match and body:
                    offset += _append_windows(out, pointer, digest, heading, body, offset)
                    body = []
                if match:
                    heading = match.group(2).strip()
                body.append(line)
                if sum(len(b) for b in body) > TARGET_CHARS * 4:  # keep the buffer bounded
                    offset += _append_windows(out, pointer, digest, heading, body, offset)
                    body = []
        _append_windows(out, pointer, digest, heading, body, offset)
    return out


def index(driver: Driver, roots: list[Root], embed=None) -> int:
    """Write chunks for every root; `embed(text) -> list[float] | None` adds vectors."""
    written = 0
    batch: list[dict] = []
    for root in roots:
        for chunk in chunks_for(root):
            if embed is not None:
                vector = embed(chunk["text"])
                if vector:
                    chunk["embedding"] = vector
            batch.append(chunk)
            if len(batch) >= BATCH:
                _flush(driver, batch)
                written += len(batch)
                batch = []
    if batch:
        _flush(driver, batch)
        written += len(batch)
    return written


def _flush(driver: Driver, batch: list[dict]) -> None:
    with driver.session() as session:
        session.run(UPSERT, chunks=batch).consume()
