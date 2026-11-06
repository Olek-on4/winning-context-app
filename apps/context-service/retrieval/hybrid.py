"""Hybrid seed retrieval: Lucene BM25 + HNSW vectors, fused with RRF k=60.

BM25 keeps exact identifiers precise; vectors catch paraphrase. Retrieval failures
degrade to an empty result, never an exception — the caller says so in the envelope.
"""

from __future__ import annotations

import os
import re

import httpx

RRF_K = 60
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"

_BM25 = """
CALL db.index.fulltext.queryNodes('chunk_text', $q) YIELD node, score
RETURN node, score
ORDER BY score DESC
LIMIT $k
"""

_VECTOR = """
CALL db.index.vector.queryNodes('chunk_embedding', $k, $vector) YIELD node, score
RETURN node, score
ORDER BY score DESC
LIMIT $k
"""

_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def search(driver, text: str, k: int = 10) -> tuple[list[dict], bool]:
    """Return (fused chunks, degraded). Degraded means neither index produced a row."""
    query = (text or "").strip()
    if not query or k < 1:
        return [], True

    channels: list[list[dict]] = []
    try:
        channels.append(_bm25(driver, query, k))
    except Exception:
        pass
    try:
        channels.append(_vector(driver, _embed(query), k))
    except Exception:
        pass

    if not any(channels):
        return [], True

    scores: dict[tuple, float] = {}
    items: dict[tuple, dict] = {}
    vias: dict[tuple, set[str]] = {}
    for channel in channels:
        for rank, chunk in enumerate(channel, 1):
            key = (chunk["path"], tuple(chunk["lines"]), chunk["text"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            items.setdefault(key, chunk)
            vias.setdefault(key, set()).add(chunk["via"])

    ranked = sorted(scores, key=lambda key: (-scores[key], key))
    fused: list[dict] = []
    for key in ranked[:k]:
        chunk = dict(items[key])
        chunk["score"] = round(scores[key], 6)
        chunk["via"] = "+".join(sorted(vias[key]))
        fused.append(chunk)
    return fused, False


def _bm25(driver, text: str, k: int) -> list[dict]:
    escaped = _LUCENE_SPECIAL.sub(r"\\\1", text[:400]).strip()
    if not escaped:
        return []
    with driver.session() as session:
        result = session.run(_BM25, q=escaped, k=k)
        return [_chunk(dict(record["node"]), record["score"], "bm25") for record in result]


def _vector(driver, vector: list[float], k: int) -> list[dict]:
    with driver.session() as session:
        result = session.run(_VECTOR, k=k, vector=list(vector))
        return [_chunk(dict(record["node"]), record["score"], "vector") for record in result]


def _embed(text: str) -> list[float]:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    model = os.environ.get("OLLAMA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    response = httpx.post(
        f"{host}/api/embed", json={"model": model, "input": text[:4000]}, timeout=5.0
    )
    response.raise_for_status()
    return list(response.json()["embeddings"][0])


def _chunk(props: dict, score: float, via: str) -> dict:
    path = str(props.get("path") or props.get("source_path") or "")
    start = props.get("start_line")
    end = props.get("end_line")
    lines = [int(start), int(end)] if start is not None and end is not None else []
    return {
        "text": str(props.get("text") or ""),
        "path": path,
        "lines": lines,
        "score": round(float(score), 6),
        "via": via,
    }
