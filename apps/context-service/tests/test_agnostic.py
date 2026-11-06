"""A corpus nobody wrote a pipeline for: extraction must be layout-blind.

The three files below use names and directories that appear nowhere in the
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


def test_reindex_drops_chunks_whose_file_vanished(tmp_path):
    """Issue 23: a deleted or renamed file must not stay retrievable forever."""
    from graph.chunks import index, sweep
    from sources import discover

    class Recorder:
        """Minimal driver stub: records the sweep statements, no Neo4j needed."""

        def __init__(self):
            self.calls = []

        def session(self):
            outer = self

            class Session:
                def run(self, query, **params):
                    outer.calls.append((query, params))

                    class Result:
                        counters = type("C", (), {"nodes_deleted": 0})()

                        def consume(self):
                            return self

                    return Result()

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            return Session()

    keep = tmp_path / "keep.md"
    keep.write_text("# kept\n\nbody\n", encoding="utf-8")
    gone = tmp_path / "gone.md"
    gone.write_text("# gone\n\nbody\n", encoding="utf-8")
    root = discover([tmp_path])[0]

    index(Recorder(), [root])          # both files indexed
    gone.unlink()
    driver = Recorder()
    index(driver, [root])              # second pass must name only the survivor

    sweeps = [params for query, params in driver.calls if "DETACH DELETE ch" in query]
    assert sweeps, "no sweep ran"
    assert sweeps[0]["prefix"] == f"{root.id}/"
    assert any(path.endswith("keep.md") for path in sweeps[0]["keep"])
    assert not any(path.endswith("gone.md") for path in sweeps[0]["keep"])
    assert sweep(driver, root, set()) == 0  # counters surface, nothing raised


def test_deploy_config_pipeline_reads_any_repo_layout(tmp_path):
    """Issue 4: compose, manifests and CODEOWNERS are facts, not Northstar specifics."""
    import subprocess

    from ingest.registry import extract
    from sources import discover

    (tmp_path / "compose.yaml").write_text(
        "services:\n  api:\n    image: x\n    depends_on:\n      - db\n  db:\n    image: y\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"dependencies": {"left-pad": "^1.0.0"}}', encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text("/api/ @team/api\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"],
        cwd=tmp_path, check=True,
    )

    claims = extract(discover([tmp_path])[0])
    triples = {(c.subject.key, c.predicate, c.object) for c in claims}

    assert ("api", "DEPENDS_ON", "db") in triples
    assert any(pred == "DEPENDS_ON" and obj == "left-pad" for _, pred, obj in triples)
    assert any(pred == "OWNS" for _, pred, _ in triples)
    assert all(c.observed_at is not None for c in claims)
