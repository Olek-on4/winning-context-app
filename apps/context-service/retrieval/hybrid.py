"""Hybrid seed retrieval: Lucene BM25 + HNSW vectors, fused with RRF k=60.

BM25 keeps exact identifiers precise; vectors catch paraphrase. Retrieval failures
degrade to an empty result, never an exception — the caller says so in the envelope.
"""

from __future__ import annotations

import os
import re

import httpx

from settings import (
    EMBED_DIM,
    EMBED_TEXT_LIMIT,
    MODEL_KEEP_ALIVE,
    MODEL_NUM_GPU,
    MODEL_TIMEOUT_S,
    QUERY_TEXT_LIMIT,
    RRF_K,
)
from settings import EMBED_MODEL as DEFAULT_EMBED_MODEL
from settings import OLLAMA_HOST as DEFAULT_HOST

_BM25 = """
CALL db.index.fulltext.queryNodes('chunk_text', $q) YIELD node, score
OPTIONAL MATCH (node)-[:IN]->(src:Source)
RETURN node, score, src.path AS path, coalesce(node.hash, src.content_hash) AS hash
ORDER BY score DESC
LIMIT $k
"""

_VECTOR = """
CALL db.index.vector.queryNodes('chunk_embedding', $k, $vector) YIELD node, score
OPTIONAL MATCH (node)-[:IN]->(src:Source)
RETURN node, score, src.path AS path, coalesce(node.hash, src.content_hash) AS hash
ORDER BY score DESC
LIMIT $k
"""

_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def search(driver, text: str, k: int = 10) -> tuple[list[dict], bool, dict[str, str]]:
    """Return (fused chunks, degraded, channel status).

    Status is `ok` (rows), `empty` (ran, no rows) or `error` (raised) per channel. A dead
    channel used to be invisible: `degraded` only reported the case where *both* were
    empty, so an index holding no vectors looked the same as a healthy lexical one.
    """
    query = (text or "").strip()
    if not query or k < 1:
        return [], True, {}

    channels: list[list[dict]] = []
    status: dict[str, str] = {}
    for name, run in (
        ("bm25", lambda: _bm25(driver, query, k)),
        ("vector", lambda: _vector(driver, _embed(query), k)),
    ):
        try:
            rows = run()
        except Exception:  # a channel that fails is reported, never fatal
            status[name] = "error"
            continue
        status[name] = "ok" if rows else "empty"
        if rows:
            channels.append(rows)

    if not any(channels):
        # #79: an index holding nothing must not look healthy. Both channels empty is
        # degraded, and the per-channel status says which one was empty versus broken.
        return [], True, status

    scores: dict[tuple, float] = {}
    items: dict[tuple, dict] = {}
    vias: dict[tuple, set[str]] = {}
    raw: dict[tuple, dict[str, float]] = {}
    for channel in channels:
        for rank, chunk in enumerate(channel, 1):
            key = (chunk["path"], tuple(chunk["lines"]), chunk["text"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            items.setdefault(key, chunk)
            vias.setdefault(key, set()).add(chunk["via"])
            # Cosine and BM25 live on different scales, so both are kept, not merged:
            # a relevance floor has to know which number it is looking at.
            raw.setdefault(key, {})[chunk["via"]] = float(chunk.get("raw_score") or 0.0)

    ranked = sorted(scores, key=lambda key: (-scores[key], key))
    fused: list[dict] = []
    for key in ranked[:k]:
        chunk = dict(items[key])
        chunk["score"] = round(scores[key], 6)
        chunk["via"] = "+".join(sorted(vias[key]))
        chunk["vector_score"] = round(raw.get(key, {}).get("vector", 0.0), 6)
        chunk["bm25_score"] = round(raw.get(key, {}).get("bm25", 0.0), 6)
        fused.append(chunk)
    return fused, any(state == "error" for state in status.values()), status


def _bm25(driver, text: str, k: int) -> list[dict]:
    escaped = _LUCENE_SPECIAL.sub(r"\\\1", text[:QUERY_TEXT_LIMIT]).strip()
    if not escaped:
        return []
    with driver.session() as session:
        result = session.run(_BM25, q=escaped, k=k)
        return [
            _chunk(dict(record["node"]), record["score"], "bm25",
                   record.get("path") or "", record.get("hash") or "")
            for record in result
        ]


def _vector(driver, vector: list[float], k: int) -> list[dict]:
    with driver.session() as session:
        result = session.run(_VECTOR, k=k, vector=list(vector))
        return [
            _chunk(dict(record["node"]), record["score"], "vector",
                   record.get("path") or "", record.get("hash") or "")
            for record in result
        ]


def _embed(text: str) -> list[float]:
    """One embedding from a local model. `num_gpu: -1` puts every layer on the GPU;
    Ollama falls back to CPU by itself when no device is visible."""
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    model = os.environ.get("OLLAMA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    options = {
        "num_gpu": int(os.environ.get("OLLAMA_NUM_GPU", MODEL_NUM_GPU)),
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", MODEL_KEEP_ALIVE),
    }
    response = httpx.post(
        f"{host}/api/embed",
        json={"model": model, "input": text[:EMBED_TEXT_LIMIT], "options": options, "keep_alive": options["keep_alive"]},
        timeout=MODEL_TIMEOUT_S,
    )
    response.raise_for_status()
    vectors = response.json().get("embeddings") or []
    if not vectors:
        raise ValueError(f"{model} returned no embedding")
    if len(vectors[0]) != EMBED_DIM:
        # The index is declared at EMBED_DIM (graph/schema.cypher); an env-selected model
        # with a different width would be rejected by Neo4j per chunk, so say it once (#79).
        raise ValueError(
            f"{model} returned a {len(vectors[0])}-d embedding but the vector index expects "
            f"{EMBED_DIM}"
        )
    return list(vectors[0])


def _chunk(props: dict, score: float, via: str, path: str = "", digest: str = "") -> dict:
    path = path or str(props.get("path") or props.get("source_path") or "")
    start = props.get("start_line")
    end = props.get("end_line")
    lines = [int(start), int(end)] if start is not None and end is not None else []
    return {
        "text": str(props.get("text") or ""),
        "path": path,
        "lines": lines,
        # The index stores it as `heading_path`; reading `heading` silently emptied it.
        "heading": str(props.get("heading_path") or props.get("heading") or ""),
        # The indexed digest, so verification compares against what was indexed rather than
        # re-deriving the live hash and thereby verifying nothing.
        "hash": str(props.get("hash") or digest or ""),
        # An image chunk has no lines; its rectangle is what the citation points at.
        "region": [int(props[k]) for k in ("region_x", "region_y", "region_w", "region_h")]
        if props.get("region_x") is not None else None,
        "score": round(float(score), 6),
        "raw_score": float(score),   # the channel's own scale, before fusion
        "via": via,
    }
