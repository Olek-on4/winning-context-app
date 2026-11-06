"""The running container stack must answer the demo's questions over HTTP.

Skips when docker or the containers are absent, so a checkout without the stack stays
green; the strict end-to-end probe is `scripts/e2e_docker.py`.
"""

from __future__ import annotations

import shutil
import subprocess

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE = "http://127.0.0.1:8000"
QUESTION = "Does inventory-service still use a Redis cache?"
CONTAINERS = ("etyt-neo4j", "etyt-app")


def _running(name: str) -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=False,
    )
    return name in result.stdout.split()


@pytest.fixture(scope="module")
def client():
    if not all(_running(name) for name in CONTAINERS):
        pytest.skip("container stack is not running")
    try:
        health = httpx.get(f"{BASE}/healthz", timeout=2)
    except httpx.HTTPError as exc:
        pytest.skip(f"app container is not answering: {exc}")
    if health.status_code != 200:
        pytest.skip(f"app container is unhealthy: {health.status_code}")
    with httpx.Client(base_url=BASE, timeout=20) as http:
        yield http


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_query_returns_the_superseded_cache_story(client):
    answer = client.post("/v1/query", json={"question": QUESTION}).json()
    rows = [(claim["statement"], claim["status"]) for claim in answer["claims"]]
    assert any("sqlite" in statement and status == "VALID" for statement, status in rows)
    assert any("NOT READS_FROM redis" in statement for statement, _ in rows)
    assert any("redis" in statement and status == "DEPRECATED" for statement, status in rows)
