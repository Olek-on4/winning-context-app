"""ncs: one driver, two transports, one loader.

    uv run python -m cli serve          # REST on :8000
    uv run python -m cli mcp            # MCP over stdio
    uv run python -m cli load <file>    # claims JSONL into the graph
    uv run python -m cli index          # chunk the corpus for hybrid search
    uv run python -m cli extract [--source <dir> ...]   # claims from any number of roots

No business logic here — every line is wiring.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from graph.chunks import index as index_chunks
from graph.loader import apply_schema, connect, load
from ingest.deterministic import extract
from models.claim import ClaimRecord
from retrieval.service import ContextService
from sources import Root, discover


def _corpus_root() -> Path:
    """Env wins; otherwise walk up from this file until the submodule is found."""
    if env := os.getenv("CORPUS_ROOT"):
        return Path(env).resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "vendor" / "att-hackathon-task"
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("corpus submodule not found; set CORPUS_ROOT")


def _sources(argv: list[str]) -> list[Root]:
    """`--source` may repeat; with none, the corpus submodule is the single root."""
    paths = [Path(arg) for arg in argv] or [_corpus_root()]
    roots = discover(paths)
    if not roots:
        raise SystemExit(f"no source directories: {', '.join(argv)}")
    return roots


def _split_sources(argv: list[str]) -> tuple[list[str], list[str]]:
    """Pull every `--source <dir>` / `--source=<dir>` out, leaving the rest untouched."""
    rest, sources, index = [], [], 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--source":
            if index + 1 >= len(argv):
                raise SystemExit("--source needs a directory")
            sources.append(argv[index + 1])
            index += 2
            continue
        if arg.startswith("--source="):
            sources.append(arg.split("=", 1)[1])
        else:
            rest.append(arg)
        index += 1
    return rest, sources


def _driver():
    return connect(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "etyt-context"),
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


def extract_claims(*sources: str) -> None:
    """`... cli extract [--source <dir> ...]`: claims from every root, one JSONL."""
    roots = _sources(list(sources))
    # Two roots may claim the same fact; claim_id is that fact's identity, so last write wins.
    claims = {claim.claim_id: claim for root in roots for claim in extract(root)}
    out = Path(os.getenv("EXTRACTED_PATH", "../../data/local/claims-extracted.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(c.model_dump_json() + "\n" for c in claims.values()), encoding="utf-8")
    print(json.dumps({"claims": len(claims), "roots": [r.id for r in roots], "path": str(out)}))


def index_corpus(*sources: str) -> None:
    """`... cli index [--source <dir> ...]`: chunk every root; embed too when a model answers."""
    from retrieval.hybrid import _embed

    roots = _sources(list(sources))
    driver = _driver()
    apply_schema(driver)
    try:
        vector = _embed("probe")
    except Exception:  # no model on this machine is a supported state, not an error
        vector = None
    def progress(done: int, total: int) -> None:
        # stderr: stdout stays the single JSON line callers parse.
        print(f"  embedded {done}/{total}", file=sys.stderr, flush=True)

    chunks = index_chunks(driver, roots, embed=_embed if vector else None, progress=progress)
    print(json.dumps({"chunks": chunks, "embedded": bool(vector), "roots": [r.id for r in roots]}))


def load_claims(*paths: str) -> None:
    """Load one or more claims JSONL files: fixtures, extracted, or both."""
    if not paths:
        raise SystemExit("usage: python -m cli load <file> [<file> ...]")
    claims = [
        ClaimRecord.model_validate_json(line)
        for path in paths
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]
    driver = _driver()
    apply_schema(driver)
    count = load(driver, claims)
    print(json.dumps({"loaded": count, "sources": list(paths)}))


if __name__ == "__main__":
    import sys

    command, *rest = sys.argv[1:] or ["serve"]
    rest, sources = _split_sources(rest)
    if command == "serve":
        serve()
    elif command == "mcp":
        serve_mcp()
    elif command == "extract":
        extract_claims(*sources)
    elif command == "index":
        index_corpus(*sources)
    elif command == "load" and rest:
        load_claims(*rest)
    else:
        raise SystemExit(
            f"usage: python -m cli [serve|mcp|load <file>|extract [--source <dir> ...]"
            f"|index [--source <dir> ...]]; got {command}"
        )
