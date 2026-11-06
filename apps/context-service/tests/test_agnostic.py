"""A corpus nobody wrote a pipeline for: extraction must be layout-blind.

The three files below use names and directories that appear nowhere in the Northstar
corpus, so passing here means the pipelines key off content, not off a known tree.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from ingest import registry
from sources import discover, root_id

FILES = {
    "schema/001-x.sql": "ALTER TABLE widget RENAME COLUMN old TO new;\n",
    "conf/ports.json": '{"widget-api": 7001}\n',
    "notes/decision.md": "# Decision\n\nStatus: Accepted\n",
}


def _corpus(base: Path) -> Path:
    for relative, text in FILES.items():
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return base


def _git(base: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(base), *args], check=True, capture_output=True, text=True)


def test_unseen_layout_extracts_with_dates_and_root_prefixed_pointers(tmp_path):
    _corpus(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "corpus")

    [root] = discover([tmp_path])
    claims = registry.extract(root)

    assert root.id == root_id(tmp_path)
    assert {c.predicate for c in claims} == {"HAS_COLUMN", "LISTENS_ON", "HAS_STATUS"}
    assert all(c.observed_at is not None for c in claims)
    assert all(c.evidence[0].path.startswith(f"{root.id}/") for c in claims)
    assert {c.evidence[0].path for c in claims} == {f"{root.id}/{relative}" for relative in FILES}


def test_directory_without_git_skips_claims_instead_of_crashing():
    with tempfile.TemporaryDirectory() as raw:
        base = _corpus(Path(raw))
        if any((parent / ".git").exists() for parent in (base, *base.parents)):
            pytest.skip("temporary directory sits inside a git work tree")

        [root] = discover([base])
        assert registry.extract(root) == []
