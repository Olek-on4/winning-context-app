"""ncs: one driver, two transports, one loader.

    uv run python -m cli serve          # REST on :8000
    uv run python -m cli mcp            # MCP over stdio
    uv run python -m cli load <file>    # claims JSONL into the graph
    uv run python -m cli index          # chunk the corpus for hybrid search
    uv run python -m cli extract        # deterministic claims from migrations + ports

No business logic here — every line is wiring.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from graph.chunks import index as index_chunks
from ingest.deterministic import extract
from graph.loader import apply_schema, connect, load
from models.claim import ClaimRecord
from retrieval.service import ContextService


def _corpus_root() -> Path:
    """Env wins; otherwise walk up from this file until the submodule is found."""
    if env := os.getenv("CORPUS_ROOT"):
        return Path(env).resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "vendor" / "att-hackathon-task"
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("corpus submodule not found; set CORPUS_ROOT")


def _driver():
    return connect(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "northstar"),
    )


def _service() -> ContextService:
    return ContextService(_driver(), _corpus_root())


def serve() -> None:
    import uvicorn

    from api.app import create_app

    uvicorn.run(create_app(_service()), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))


def serve_mcp() -> None:
    from mcp_server.server import serve as run

    run(_service())


def extract_claims() -> None:
    """`... cli extract`: deterministic claims from migrations and ports.json."""
    root = _corpus_root()
    claims = extract(root)
    out = Path(os.getenv("EXTRACTED_PATH", "../../data/local/claims-extracted.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(c.model_dump_json() for c in claims) + "\n", encoding="utf-8")
    print(json.dumps({"claims": len(claims), "path": str(out)}))


def index_corpus() -> None:
    """`... cli index`: chunk the corpus and fill the BM25 index (no model needed)."""
    driver = _driver()
    apply_schema(driver)
    print(json.dumps({"chunks": index_chunks(driver, _corpus_root())}))


def load_claims(path: str) -> None:
    """Load a claims JSONL: `ncs-load data/fixtures/claims-sample.jsonl`."""
    claims = [ClaimRecord.model_validate_json(line) for line in Path(path).read_text().splitlines() if line.strip()]
    driver = _driver()
    apply_schema(driver)
    count = load(driver, claims)
    print(json.dumps({"loaded": count, "source": path}))


if __name__ == "__main__":
    import sys

    command, *rest = sys.argv[1:] or ["serve"]
    if command == "serve":
        serve()
    elif command == "mcp":
        serve_mcp()
    elif command == "extract":
        extract_claims()
    elif command == "index":
        index_corpus()
    elif command == "load" and rest:
        load_claims(rest[0])
    else:
        raise SystemExit(f"usage: python -m cli [serve|mcp|load <file>]; got {command}")
