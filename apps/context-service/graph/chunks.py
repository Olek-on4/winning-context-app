"""Chunk any text tree for hybrid search — streamed, batched, root-agnostic.

Chunks are the retrieval unit only: rebuildable from a pointer, never cited. Text is
read one line at a time and written to the graph in batches, so a 10 MB file costs a
line buffer, not 10 MB of RAM.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Self

from neo4j import Driver

from settings import CHUNK_BATCH as BATCH
from settings import CHUNK_TARGET_CHARS as TARGET_CHARS
from settings import EMBED_DIM
from sources import Root, iter_files

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# EMBED_DIM is the width the Neo4j vector index declares (graph/schema.cypher). One
# constant, so the embedder, the index and the failure message cannot disagree (#79).
UPSERT = """
UNWIND $chunks AS c
MERGE (ch:Chunk {id: c.id})
SET ch.text = c.text, ch.heading_path = c.heading, ch.token_count = c.tokens,
    ch.embedding = c.embedding, ch.root = c.root, ch.path = c.path,
    ch.start_line = c.start_line, ch.end_line = c.end_line, ch.hash = c.hash,
    ch.region_x = c.region_x, ch.region_y = c.region_y,
    ch.region_w = c.region_w, ch.region_h = c.region_h
MERGE (src:Source {path: c.path})
SET src.content_hash = c.hash
MERGE (ch)-[:IN]->(src)
"""


def _line_starts(body: list[str]) -> list[int]:
    """Char offset in `"".join(body)` where each source line begins."""
    starts, position = [], 0
    for line in body:
        starts.append(position)
        position += len(line)
    return starts


def _windows(
    pointer: str,
    digest: str,
    heading: str,
    root_id: str,
    text: str,
    base: int,
    starts: list[int],
    first_line: int,
):
    """`base` is the char offset of `text` in its file, so ids stay unique when one
    heading yields several windows — a per-body index would collide and lose text.

    `start_line`/`end_line` are the file lines the window covers, mapped through `starts`
    (one text offset per source line) rather than counting newlines: a stripped body does
    not start at offset zero. Hybrid search reads both, and a citation without a line
    range cannot be resolved back to bytes (#83).
    """
    for index in range(0, len(text), TARGET_CHARS):
        part = text[index : index + TARGET_CHARS]
        # Whitespace at either edge carries no content: cite the lines the words are on.
        head = index + len(text[index:]) - len(text[index:].lstrip())
        trimmed = len(part.rstrip())
        tail = index + max(trimmed, 1) - 1
        first = bisect.bisect_right(starts, head) - 1
        last = max(first, bisect.bisect_right(starts, max(tail, head)) - 1)
        yield {
            "id": hashlib.sha256(f"{pointer}|{heading}|{base + index}".encode()).hexdigest()[:16],
            "text": f"{heading}\n{part}".strip() if heading else part,
            "heading": heading,
            "tokens": len(part) // 4,
            "path": pointer,
            "root": root_id,
            "start_line": first + first_line,
            "end_line": last + first_line,
            "hash": digest,
            # present on every row so one UNWIND can set them; null means "text chunk"
            "region_x": None, "region_y": None, "region_w": None, "region_h": None,
        }


def _append_windows(
    out: list[dict],
    pointer: str,
    digest: str,
    heading: str,
    root_id: str,
    body: list[str],
    base: int,
    first_line: int,
) -> tuple[int, int]:
    """Append this body's windows; return (chars, lines) it advanced the file by."""
    # "".join, not "\n".join: every line already ends with its newline, and an inserted
    # separator double-spaced the chunk text — inflating tokens and, worse, breaking the
    # char-offset-to-line map that `start_line` depends on (#83).
    joined = "".join(body)
    text = joined.strip()
    if not text:
        return 0, len(body)
    # `.strip()` removes leading whitespace, so every line start shifts by that many chars;
    # blank leading lines shift past the text entirely and are never cited.
    lead = len(joined) - len(joined.lstrip())
    starts = [start - lead for start in _line_starts(body)]
    out.extend(_windows(pointer, digest, heading, root_id, text, base, starts, first_line))
    return len(text), len(body)


def _image_chunk(root: Root, relative: Path, digest: str) -> list[dict]:
    """One chunk per picture: OCR text, cited by the whole-image rectangle.

    Without this a PNG never enters the index — the walker opens every file as UTF-8 — so
    diagram text could be extracted and still be unsearchable, which is the failure mode
    ADR-0012 exists to remove.
    """
    import logging

    from rapidocr import RapidOCR

    from sources import image_size

    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    texts = list(RapidOCR()(str(root.path / relative)).txts or [])
    text = "\n".join(t.strip() for t in texts if t and t.strip())
    if not text:
        return []
    width, height = image_size(root.path / relative)
    pointer = root.pointer(relative)
    return [{
        "id": hashlib.sha256(f"{pointer}|image|0".encode()).hexdigest()[:16],
        "text": text,
        "heading": "",
        "tokens": len(text) // 4,
        "path": pointer,
        "root": root.id,
        "start_line": 1,
        "end_line": 1,
        "hash": digest,
        "region_x": 0,
        "region_y": 0,
        "region_w": width,
        "region_h": height,
    }]


def chunks_for(root: Root) -> list[dict]:
    """Heading-aware, line-streamed. One list per root; the caller flushes it."""
    out: list[dict] = []
    for relative, digest in iter_files(root, claimable=lambda p: p.suffix.lower() in {".png", ".gif"}):
        if relative.suffix.lower() in {".png", ".gif"}:
            out.extend(_image_chunk(root, relative, digest))
            continue
        pointer = root.pointer(relative)
        heading, body, offset, line_no = "", [], 0, 1
        with (root.path / relative).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = HEADING.match(line)
                if match and body:
                    consumed, lines = _append_windows(
                        out, pointer, digest, heading, root.id, body, offset, line_no
                    )
                    offset, line_no = offset + consumed, line_no + lines
                    body = []
                if match:
                    heading = match.group(2).strip()
                body.append(line)
                if sum(len(b) for b in body) > TARGET_CHARS * 4:  # keep the buffer bounded
                    consumed, lines = _append_windows(
                        out, pointer, digest, heading, root.id, body, offset, line_no
                    )
                    offset, line_no = offset + consumed, line_no + lines
                    body = []
        _append_windows(out, pointer, digest, heading, root.id, body, offset, line_no)
    return out


SWEEP = """
MATCH (ch:Chunk)-[:IN]->(s:Source)
WHERE s.path STARTS WITH $prefix AND NOT s.path IN $keep
DETACH DELETE ch
"""

ORPHAN_SOURCES = """
MATCH (s:Source)
WHERE s.path STARTS WITH $prefix AND NOT (s)<-[:IN]-(:Chunk) AND NOT (s)<-[:IN]-(:Span)
DETACH DELETE s
"""


def sweep(driver: Driver, root: Root, keep: set[str]) -> int:
    """Delete chunks whose file vanished or was renamed, scoped to this root's prefix.

    Only root-prefixed sources are swept: fixture spans store bare corpus paths, and those
    Sources belong to claims, not to the chunk index.
    """
    prefix = f"{root.id}/"
    with driver.session() as session:
        removed = session.run(SWEEP, prefix=prefix, keep=sorted(keep)).consume().counters.nodes_deleted
        session.run(ORPHAN_SOURCES, prefix=prefix).consume()
    return removed


class IndexOutcome(int):
    """The written count, plus what the CLI must print: `{"chunks": n, "embedded": bool}`.

    Subclassing int keeps every existing caller and test working (`written == 42`),
    while the CLI can report an honest `embedded` flag and, when vectors were skipped,
    a `reason` naming both widths (#79).
    """

    def __new__(cls, written: int, *, embedded: bool, reason: str | None = None) -> Self:
        outcome = super().__new__(cls, written)
        outcome.embedded = embedded
        outcome.reason = reason
        return outcome

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"chunks": int(self), "embedded": self.embedded}
        if self.reason:
            out["reason"] = self.reason
        return out


def probe_embedding(embed) -> str | None:
    """One throwaway embedding: `None` when vectors will be written, else the reason.

    Called before any chunk is written, because the old CLI swallowed the exception
    and indexed lexically with no signal: `embedded: true` described an index with no
    vectors at all (#79).
    """
    try:
        vector = embed("probe")
    except Exception as exc:
        reason = f"embedding unavailable ({type(exc).__name__}: {exc})"
        _warn(reason)
        return reason
    if not vector:
        reason = "embedding model returned no vector"
        _warn(reason)
        return reason
    actual = len(vector)
    if actual != EMBED_DIM:
        reason = (
            f"embedding width {actual} does not match the index width {EMBED_DIM} "
            f"(`vector.dimensions` in graph/schema.cypher); indexing text only"
        )
        _warn(reason)
        return reason
    return None


def _warn(reason: str) -> None:
    """stderr: stdout stays the single JSON line the CLI contract promises."""
    print(json.dumps({"warning": "vectors skipped", "reason": reason}), file=sys.stderr, flush=True)


def index(driver: Driver, roots: list[Root], embed=None, progress=None) -> IndexOutcome:
    """Write chunks for every root; `embed(text) -> list[float] | None` adds vectors.

    `progress(done, total)` exists because CPU embedding takes minutes, and a silent
    wait looks like a hang. A vector that is not `EMBED_DIM` wide is refused before any
    write, so the outcome can never call a lexical-only index "embedded".
    """
    reason = probe_embedding(embed) if embed is not None else "no embedding model was requested"
    may_embed = embed if reason is None else None
    written = 0
    total = sum(len(chunks_for(root)) for root in roots) if may_embed is not None else 0
    batch: list[dict] = []
    for root in roots:
        current = chunks_for(root)
        sweep(driver, root, {chunk["path"] for chunk in current})
        for chunk in current:
            if may_embed is not None:
                vector = may_embed(chunk["text"])
                if vector:
                    chunk["embedding"] = vector
            batch.append(chunk)
            if len(batch) >= BATCH:
                _flush(driver, batch)
                written += len(batch)
                batch = []
                if progress and total:
                    progress(written, total)
    if batch:
        _flush(driver, batch)
        written += len(batch)
    if progress and total:
        progress(written, total)
    embedded = may_embed is not None
    return IndexOutcome(written, embedded=embedded, reason=None if embedded else reason)


def _flush(driver: Driver, batch: list[dict]) -> None:
    with driver.session() as session:
        session.run(UPSERT, chunks=batch).consume()
