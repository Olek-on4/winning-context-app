"""End-to-end probe against the container stack: REST on :8000 and MCP over `docker run -i`.
`rehearse.py` proves bring-up from source; this proves the answers survive the boundary.

    cd apps/context-service && uv run python ../../scripts/e2e_docker.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "neo4j" / "compose.yaml"
BASE = "http://127.0.0.1:8000"
QUESTION = "Does inventory-service still use a Redis cache?"
CONTAINERS = ("etyt-neo4j", "etyt-app")
HEALTH_TIMEOUT = 120
PASS: list[tuple[str, bool, str]] = []


def sh(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(args), capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", f"docker timed out after {timeout:.0f}s")


def check(name: str, ok: bool, detail: str = "") -> None:
    PASS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def http(path: str, body: dict | None = None) -> str:
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                                     headers={"content-type": "application/json"} if body else {})
    return urllib.request.urlopen(request, timeout=20).read().decode()


def healthy() -> bool:
    names = sh("docker", "ps", "--format", "{{.Names}}").stdout.split()
    template = "{{.State.Status}}:{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
    return all(name in names and sh("docker", "inspect", "--format", template, name).stdout.strip() == "running:healthy"
               for name in CONTAINERS)


def ensure_up() -> bool:
    if healthy():
        return True
    # First run may pull images, so compose gets twice the health budget; health alone stays capped.
    up = sh("docker", "compose", "-f", str(COMPOSE), "up", "-d", timeout=2 * HEALTH_TIMEOUT)
    if up.returncode:
        print(up.stderr.strip()[-400:])  # compose's own reason beats a bare timeout
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline and not healthy():
        time.sleep(2)
    return healthy()


def mcp() -> None:
    """Drive the stdio server exactly as a client does, reading until each id answers."""
    image, _, project = sh("docker", "inspect", "etyt-app", "--format",
                           '{{.Config.Image}} {{index .Config.Labels "com.docker.compose.project"}}').stdout.strip().partition(" ")
    command = [
        "docker", "run", "-i", "--rm", "--network", f"{project or 'neo4j'}_default",
        "-e", "NEO4J_URI=bolt://neo4j:7687", "-e", "NEO4J_USER=neo4j", "-e", "NEO4J_PASSWORD=etyt-context",
        "-e", "CORPUS_ROOT=/repo/vendor/att-hackathon-task",
        "-v", f"{REPO}:/repo:ro", "-v", f"{REPO / 'data'}:/data",
        image, "python", "-m", "cli", "mcp",
    ]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def send(message: dict) -> None:
        print(json.dumps(message), file=proc.stdin, flush=True)

    def recv(want: int) -> dict:
        while line := proc.stdout.readline():
            line = line.strip()
            if not line.startswith("{"):  # docker may mix pull/build noise into stdout
                continue
            if (message := json.loads(line)).get("id") == want:
                return message
        raise EOFError(f"MCP closed before replying to id {want}")

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "e2e-docker", "version": "0"}}})
        init = recv(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = sorted(tool["name"] for tool in recv(2)["result"]["tools"])
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "context_search", "arguments": {"question": QUESTION}}})
        payload = json.loads(recv(3)["result"]["content"][0]["text"])
    finally:
        proc.stdin.close()
        proc.wait(timeout=20)
    check("MCP handshake", bool(init["result"]["serverInfo"]), init["result"]["serverInfo"]["name"])
    check("MCP lists 4 tools", len(tools) == 4, ",".join(tools))
    check("MCP context_search answers", bool(payload["claims"]), f"{len(payload['claims'])} claims")


def main() -> int:
    up = ensure_up()
    check("containers up", up, " ".join(CONTAINERS) if up else f"not healthy within {HEALTH_TIMEOUT}s")
    if not up:
        return 1
    check("healthz", json.loads(http("/healthz"))["status"] == "ok", BASE)
    answer = json.loads(http("/v1/query", {"question": QUESTION}))
    rows = [(claim["statement"], claim["status"]) for claim in answer["claims"]]
    check("T1 has a VALID sqlite row", any("sqlite" in s and st == "VALID" for s, st in rows))
    check("T1 has NOT READS_FROM redis", any("NOT READS_FROM redis" in s for s, _ in rows))
    check("T1 has a DEPRECATED redis row", any("redis" in s and st == "DEPRECATED" for s, st in rows),
          f"{len(rows)} claims, degraded={answer['degraded']}")
    check("span resolver returns the ADR",
          "Remove Redis" in http("/v1/span?path=docs/adr/003-stock-cache.md&start=6&end=6"))
    mcp()
    failed = [name for name, ok, _ in PASS if not ok]
    print("\ne2e:", "PASS" if not failed else f"{len(failed)} FAILED — {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
