"""Cold-start rehearsal: wipe, rebuild, serve, then walk the demo's own steps.

This is the part of the rehearsal a machine can do — it proves bring-up works from an
empty graph and that every command in docs/demo.md still answers. Saying the words is
still a human job.

    cd apps/context-service && uv run python ../../scripts/rehearse.py
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "apps" / "context-service"
CORPUS = REPO / "vendor" / "att-hackathon-task"
PORT = int(os.environ.get("REHEARSE_PORT", "8099"))
PASS: list[tuple[str, bool, str]] = []


def run(*args: str) -> str:
    result = subprocess.run(["uv", "run", *args], cwd=APP, capture_output=True, text=True, check=False)
    if result.returncode:
        raise SystemExit(f"{' '.join(args)} failed:\n{result.stderr[-1500:]}")
    return result.stdout.strip()


def check(name: str, ok: bool, detail: str = "") -> None:
    PASS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def post(path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(request, timeout=20).read())


def main() -> int:
    if not CORPUS.is_dir():
        print("corpus submodule missing: git submodule update --init")
        return 2

    # 1. clean graph, so this is a cold start and not a lucky cache
    run("python", "-c", "from graph.loader import connect;d=connect('bolt://localhost:7687','neo4j','etyt-context');s=d.session();s.run('MATCH (n) DETACH DELETE n');d.close()")

    # 2. the three bring-up commands from docs/demo.md
    extract = json.loads(run("python", "-m", "cli", "extract"))
    check("extract", extract["claims"] > 10, f"{extract['claims']} claims")
    load = json.loads(run(
        "python", "-m", "cli", "load",
        str(REPO / "data/fixtures/claims-sample.jsonl"),
        str(REPO / "data/local" / "claims-extracted.jsonl"),
    ))
    check("load", load["loaded"] > 40, f"{load['loaded']} claims")
    index = json.loads(run("python", "-m", "cli", "index"))
    check("index", index["chunks"] > 50, f"{index['chunks']} chunks, embedded={index['embedded']}")

    # 3. serve, then walk the script
    server = subprocess.Popen(
        ["uv", "run", "python", "-m", "cli", "serve"],
        cwd=APP, env={**os.environ, "PORT": str(PORT)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            check("serve", False, "server never answered")
            return 1
        check("serve", True, f":{PORT}")

        t1 = post("/v1/query", {"question": "Does inventory-service still use a Redis cache?"})
        rows = [(c["statement"], c["status"]) for c in t1["claims"]]
        has_sqlite = any("sqlite" in name for name, _ in rows)
        has_stale_redis = any("redis" in name and status == "DEPRECATED" for name, status in rows)
        check("T1 answers sqlite + deprecated redis", has_sqlite and has_stale_redis,
              f"{len(rows)} claims, degraded={t1['degraded']}")
        check("T1 cites the ADR",
              "docs/adr/003-stock-cache.md" in {c["path"] for claim in t1["claims"] for c in claim["citations"]})

        past = post("/v1/query", {"question": "Does inventory-service still use a Redis cache?", "as_of": "2026-03-01"})
        past_rows = {c["statement"]: c["status"] for c in past["claims"]}
        redis_valid = any("redis" in name and status == "VALID" for name, status in past_rows.items())
        sqlite_hidden = not any("sqlite" in name for name in past_rows)
        check("time travel: redis VALID, sqlite absent in March", redis_valid and sqlite_hidden,
              f"{sorted(past_rows)}")

        t2 = post("/v1/query", {"question": "What fields does the users table have?"})
        check("T2 shows account_status", any("account_status" in c["statement"] for c in t2["claims"]))

        plan = post("/v1/plan", {"question": "what disagrees about stock caching?"})
        check("plan endpoint returns a CQP", plan.get("intent") == "CONFLICTS", plan.get("intent", "?"))

        span = urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/v1/span?path=docs/adr/003-stock-cache.md&start=6&end=6", timeout=10
        ).read().decode()
        check("span resolver returns real bytes", "Remove Redis" in span)
    finally:
        os.killpg(server.pid, signal.SIGINT)
        server.wait(timeout=10)

    # 4. the IDE loop: MCP handshake over stdio, exactly as a client does it
    mcp = subprocess.Popen(
        ["uv", "run", "python", "-m", "cli", "mcp"], cwd=APP,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )
    def send(message: dict) -> None:
        mcp.stdin.write(json.dumps(message) + "\n"); mcp.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "rehearse", "version": "0"}}})
    init = json.loads(mcp.stdout.readline())
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = json.loads(mcp.stdout.readline())
    names = sorted(t["name"] for t in tools["result"]["tools"])
    check("MCP handshake", bool(init["result"]["serverInfo"]), ",".join(names))
    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "context_search", "arguments": {"question": "Does inventory-service still use a Redis cache?"}}})
    call = json.loads(mcp.stdout.readline())
    payload = json.loads(call["result"]["content"][0]["text"])
    check("MCP context_search answers", bool(payload["claims"]), f"{len(payload['claims'])} claims")
    mcp.stdin.close()
    mcp.wait(timeout=10)

    failed = [name for name, ok, _ in PASS if not ok]
    print("\nrehearsal:", "READY" if not failed else f"{len(failed)} FAILED — {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
