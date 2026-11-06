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
OPTIONAL MATCH (node)-[:IN]->(src:Source)
RETURN node, score, src.path AS path
ORDER BY score DESC
LIMIT $k
"""

_VECTOR = """
CALL db.index.vector.queryNodes('chunk_embedding', $k, $vector) YIELD node, score
OPTIONAL MATCH (node)-[:IN]->(src:Source)
RETURN node, score, src.path AS path
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
        return [], True, status

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
    return fused, any(state == "error" for state in status.values()), status


def _bm25(driver, text: str, k: int) -> list[dict]:
    escaped = _LUCENE_SPECIAL.sub(r"\\\1", text[:400]).strip()
    if not escaped:
        return []
    with driver.session() as session:
        result = session.run(_BM25, q=escaped, k=k)
        return [_chunk(dict(record["node"]), record["score"], "bm25", record.get("path") or "") for record in result]


def _vector(driver, vector: list[float], k: int) -> list[dict]:
    with driver.session() as session:
        result = session.run(_VECTOR, k=k, vector=list(vector))
        return [_chunk(dict(record["node"]), record["score"], "vector", record.get("path") or "") for record in result]


def _embed(text: str) -> list[float]:
    """One embedding from a local model. `num_gpu: -1` puts every layer on the GPU;
    Ollama falls back to CPU by itself when no device is visible."""
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    model = os.environ.get("OLLAMA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    options = {
        "num_gpu": int(os.environ.get("OLLAMA_NUM_GPU", "-1")),
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "30m"),
    }
    response = httpx.post(
        f"{host}/api/embed",
        json={"model": model, "input": text[:4000], "options": options, "keep_alive": options["keep_alive"]},
        timeout=60.0,
    )
    response.raise_for_status()
    vectors = response.json().get("embeddings") or []
    if not vectors or len(vectors[0]) != 768:
        raise ValueError(f"expected a 768-d embedding from {model}")
    return list(vectors[0])


def _chunk(props: dict, score: float, via: str, path: str = "") -> dict:
    path = path or str(props.get("path") or props.get("source_path") or "")
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
