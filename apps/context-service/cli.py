"""ncs: one driver, two transports, one loader.

    uv run python -m cli serve          # REST on :8000
    uv run python -m cli mcp            # MCP over stdio
    uv run python -m cli load <file>    # claims JSONL into the graph, span-gated
    uv run python -m cli index          # chunk the corpus for hybrid search
    uv run python -m cli extract [--source <type>:<dir> ...]   # claims from any number of roots

No business logic here — every line is wiring.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from graph.chunks import index as index_chunks
from graph.loader import apply_schema, connect, load
from ingest.deterministic import extract
from ingest.gates import verify
from ingest.ontology import validate as ontology_validate
from logging_setup import logger
from models.claim import ClaimRecord
from retrieval.service import ContextService
from sources import Root, SpanStore, discover, probe, split_typed

USAGE = """usage: python -m cli <command> [args]

  serve                                   REST on :8000
  mcp                                     MCP over stdio
  load <file> [<file> ...]                claims JSONL into the graph (span-gated)
  index [--source [<type>:]<dir> ...]     chunk every root for hybrid search
  extract [--source [<type>:]<dir> ...]   claims from any number of roots
          [--accept-opt-in NAME]          also run an opt-in module (asked if a TTY)
          [--decline-opt-in NAME]         pin a module off even when installed

--source may repeat and accepts `<type>:<dir>`. Types: adr, api-specs, code, config,
docs, sql. A root whose files do not match its declared type is reported on stderr and
skipped; only an empty survivor set is fatal. A bare --source <dir> is typed by path.
With no --source at all, the corpus submodule is the only root."""


def _corpus_root() -> Path:
    """Env wins; otherwise walk up from this file until the submodule is found."""
    if env := os.getenv("CORPUS_ROOT"):
        return Path(env).resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "vendor" / "att-hackathon-task"
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("corpus submodule not found; set CORPUS_ROOT")


def _default_extract_path() -> Path:
    """`data/local/` beside the checkout, not beside the caller's cwd (issue 85)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "data" / "fixtures").is_dir():
            return parent / "data" / "local" / "claims-extracted.jsonl"
    return Path.cwd() / "claims-extracted.jsonl"


def _sources(argv: list[str]) -> list[Root]:
    """Typed or bare `--source` values; the corpus submodule when none is given (issue 69).

    A declared type is probed before extraction, and a mismatch is a reported skip: the
    operator asked for ADRs and gets a reason, not a silent empty run or a wrong claim set.
    """
    if not argv:
        return discover([_corpus_root()])
    roots: dict[Path, Root] = {}
    for arg in argv:
        try:
            kind, path = split_typed(arg)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        found = discover([path])
        if not found:
            print(f"source {path}: not a directory; skipped", file=sys.stderr)
            continue
        for root in found:
            if kind is not None:
                ok, reason = probe(kind, root)
                if not ok:
                    print(f"source {root.id} ({root.path}) claimed {kind}, found {reason}; skipped", file=sys.stderr)
                    continue
                root = replace(root, kind=kind)
            roots[root.path] = root  # last declaration of the same tree wins, deterministically
    if not roots:
        raise SystemExit(f"no usable source directories: {', '.join(argv)}")
    return list(roots.values())


def _opt_in_env(name: str) -> frozenset[str]:
    """`ETYT_ACCEPT_OPT_IN=a,b` is the unattended form; the flag is the typed one."""
    return frozenset(n.strip() for n in os.getenv(name, "").split(",") if n.strip())


def _opt_in_flags(argv: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Pull `--accept-opt-in NAME` / `--decline-opt-in NAME` (either form) out of argv."""
    rest: list[str] = []
    accepted: list[str] = []
    rejected: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in {"--accept-opt-in", "--decline-opt-in"}:
            if index + 1 >= len(argv):
                raise SystemExit(f"{arg} needs a module name")
            (accepted if arg == "--accept-opt-in" else rejected).append(argv[index + 1])
            index += 2
            continue
        for flag, sink in (("--accept-opt-in=", accepted), ("--decline-opt-in=", rejected)):
            if arg.startswith(flag):
                sink.append(arg.split("=", 1)[1])
                break
        else:
            rest.append(arg)
        index += 1
    return rest, accepted, rejected


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


def _served_roots() -> list[Root]:
    """Roots the *server* may read citations from — `SOURCES` (colon-separated) or the corpus.

    Extraction can point at any directory; unless serving knows the same list, every
    citation from an extra root fails verification at query time.
    """
    env = os.getenv("SOURCES")
    paths = [Path(part).expanduser() for part in env.split(os.pathsep)] if env else [_corpus_root()]
    roots = discover(paths)
    if not roots:
        raise SystemExit(f"SOURCES names no existing directory: {env}")
    return roots


def _service() -> ContextService:
    return ContextService(_driver(), SpanStore(_served_roots()))


def serve() -> None:
    import uvicorn

    from api.app import create_app

    uvicorn.run(
        create_app(_service()),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        # The middleware logs every request with its duration; a second access line would
        # only duplicate it.
        access_log=False,
    )


def serve_mcp() -> None:
    from mcp_server.server import serve as run

    run(_service())


def extract_claims(*sources: str, accepted: frozenset[str] = frozenset(), rejected: frozenset[str] = frozenset()) -> None:
    """`... cli extract [--source [<type>:]<dir> ...]`: claims from every root, one JSONL."""
    log = logger("extract")
    roots = _sources(list(sources))
    # A terminal gets asked; a pipeline or cron job must pass the flag instead.
    ask = (lambda question: input(question)) if sys.stdin.isatty() else None
    optins: dict[str, str] = {}
    log.info("extracting from %s", ", ".join(root.id for root in roots))
    # Two roots may claim the same fact; claim_id is that fact's identity, so last write wins.
    claims: dict[str, ClaimRecord] = {}
    for root in roots:
        extracted = extract(root, accepted=accepted, rejected=rejected, ask=ask, record=optins)
        if not extracted:
            # Never a silent zero: an unsupported layout is a gap the operator must see (issue 84).
            log.warning("no claims extracted from %s (%s)", root.id, root.path)
        claims.update({claim.claim_id: claim for claim in extracted})
    log.info("extracted %d claim(s)", len(claims))
    out = Path(os.getenv("EXTRACTED_PATH") or _default_extract_path())
    out.parent.mkdir(parents=True, exist_ok=True)
    # Sorted by claim_id: a repeat run must produce the same bytes, and dict order is not a promise.
    ordered = sorted(claims.values(), key=lambda c: c.claim_id)
    out.write_text("".join(c.model_dump_json() + "\n" for c in ordered), encoding="utf-8")
    summary: dict[str, object] = {"claims": len(claims), "roots": [r.id for r in roots], "path": str(out)}
    if optins:  # auditable consent: what ran, what was refused, and why
        summary["optins"] = dict(sorted(optins.items()))
    print(json.dumps(summary))


def index_corpus(*sources: str) -> None:
    """`... cli index [--source [<type>:]<dir> ...]`: chunk every root; embed too when a model answers."""
    from graph.claims_embed import build as build_claim_vectors
    from graph.vocab import build as build_vocab
    from retrieval.hybrid import _embed

    log = logger("index")
    roots = _sources(list(sources))
    log.info("indexing %s", ", ".join(root.id for root in roots))
    driver = _driver()
    apply_schema(driver)
    def progress(done: int, total: int) -> None:
        # stdout stays the single JSON line callers parse.
        log.info("embedded %d/%d", done, total)

    # index() probes the embedding width itself and reports a mismatch instead of
    # silently indexing lexical-only (issue 79).
    outcome = index_chunks(driver, roots, embed=_embed, progress=progress)
    # The vocabulary is what turns a question into anchors, so it is indexed with the
    # chunks: one embed pass, and a corpus gets its own dictionary for free.
    log.info("chunks: %s, embedded=%s", outcome.as_dict()["chunks"], outcome.as_dict()["embedded"])
    vocab = build_vocab(driver, _embed) if outcome.as_dict()["embedded"] else 0
    # Claims are embedded after the vocabulary so the semantic channel and the anchors are
    # always built from the same model in the same pass.
    vectors = (
        build_claim_vectors(driver, _embed)
        if outcome.as_dict()["embedded"]
        else {"offered": 0, "matched": 0}
    )
    if vectors["matched"] != vectors["offered"]:
        # A silent partial write is how an earlier run reported 311 vectors with none in
        # the graph; the graph is the only thing that can confirm a write.
        print(
            f"  claim vectors: {vectors['matched']}/{vectors['offered']} matched existing claims",
            file=sys.stderr,
            flush=True,
        )
    print(
        json.dumps(
            {
                **outcome.as_dict(),
                "vocab": vocab,
                "claim_vectors": vectors["matched"],
                "claim_vectors_offered": vectors["offered"],
                "roots": [r.id for r in roots],
            }
        )
    )


def load_claims(*paths: str) -> None:
    """Load one or more claims JSONL files: fixtures, extracted, or both.

    Every excerpt is resolved against the file its span cites before the claim is written;
    a claim whose text is not there is dropped with a reason and counted (issue 73).
    Pointers resolve through `SOURCES` (or the corpus), so load must see the roots that
    extraction read. Pointer-only fixture claims carry no excerpt and load ungeated.
    """
    if not paths:
        raise SystemExit("usage: python -m cli load <file> [<file> ...]")
    claims = [
        ClaimRecord.model_validate_json(line)
        for path in paths
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    log = logger("load")
    log.info("read %d claim(s) from %d file(s)", len(claims), len(paths))
    claims, rejected = ontology_validate(claims)
    for rejection in rejected:
        span = rejection.claim.evidence[0]
        # A dropped claim is a fact about the corpus, so it is an error line with its span.
        log.error("ontology rejected %s:%s: %s", span.path, span.start_line, rejection.reason)
    verified, counts = verify(claims, SpanStore(_served_roots()))
    driver = _driver()
    apply_schema(driver)
    # Replace, always: re-loading a file is a re-extraction, and a version bump must
    # remove what it superseded instead of leaving both opinions in the graph.
    count = load(driver, verified, replace=True)
    log.info("loaded %d claim(s), %d rejected by the gates", count, len(rejected))
    print(json.dumps({"loaded": count, "sources": list(paths), **counts.as_json(),
                      "ontology_rejected": len(rejected)}))


def main(argv: list[str]) -> None:
    """Dispatch one command; `--help` anywhere prints usage and exits 0."""
    command, *rest = argv or ["serve"]
    rest, sources = _split_sources(rest)
    if command in {"-h", "--help", "help"} or any(arg in {"-h", "--help"} for arg in rest):
        print(USAGE)
        return
    if command == "serve":
        serve()
    elif command == "mcp":
        serve_mcp()
    elif command == "extract":
        rest, accepted, rejected = _opt_in_flags(rest)
        if rest:  # a stray flag or bare dir used to be swallowed; both are mistakes
            raise SystemExit(f"unexpected arguments {rest}; pass directories with --source\n{USAGE}")
        extract_claims(
            *sources,
            accepted=frozenset(accepted) | _opt_in_env("ETYT_ACCEPT_OPT_IN"),
            rejected=frozenset(rejected) | _opt_in_env("ETYT_DECLINE_OPT_IN"),
        )
    elif command == "index":
        if rest:
            raise SystemExit(f"unexpected arguments {rest}; pass directories with --source\n{USAGE}")
        index_corpus(*sources)
    elif command == "load" and rest:
        load_claims(*rest)
    else:
        raise SystemExit(f"{USAGE}\ngot {command!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
